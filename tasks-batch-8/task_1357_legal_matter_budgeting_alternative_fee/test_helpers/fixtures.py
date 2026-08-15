"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use a lenient 2xx validator so failures surface as
clear "Setup failed" errors, not confusing assertion failures.

Identity threading: BillingPartner / ManagingPartner / Timekeeper are
entity-backed roles, so any ownership-gated call is made with headers built
from the acting Timekeeper's real id (make_*_headers), never the unbound
fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_budget_amendment_payload,
    create_client_payload,
    create_fee_arrangement_payload,
    create_firm_payload,
    create_matter_payload,
    create_phase_budget_payload,
    create_time_entry_payload,
    create_timekeeper_payload,
    create_write_down_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_billing_partner_headers,
    make_managing_partner_headers,
    make_timekeeper_headers,
)

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["pricing_analyst_headers"]
CLIENT_CONTACT = TEST_USERS["client_contact_headers"]

DEFAULT_CLOCK = TEST_DEFAULTS["DEFAULT_CLOCK"]
AFTER_YEAR_END_CLOCK = TEST_DEFAULTS["AFTER_YEAR_END_CLOCK"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}")


def _ok(step, resp, expected=None):
    data = get_success_data(resp)
    if expected is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected, (
            f"Setup failed at {step}: expected status {expected}, "
            f"got {status}")
    return data


# ---------------------------------------------------------------------------
# Tier 1 — firm / roster / client / matter stand-up
# ---------------------------------------------------------------------------

def setup_firm(fiscal_year_start_month=1, name=None, set_clock=True):
    """Create a firm and (by default) pin the logical clock to the default
    startup instant so period derivation is deterministic."""
    firm = _ok("create_firm", api_client.create_firm(
        create_firm_payload(
            fiscal_year_start_month=fiscal_year_start_month,
            **({"name": name} if name else {})),
        ADMIN))
    if set_clock:
        _ok("set_current_utc", api_client.set_current_utc(
            {"to_iso8601": DEFAULT_CLOCK}, ADMIN))
    return firm


def set_clock(to_iso8601: str):
    _ok("set_current_utc", api_client.set_current_utc(
        {"to_iso8601": to_iso8601}, ADMIN))


def add_timekeeper(firm_id, **overrides):
    return _ok("create_timekeeper", api_client.create_timekeeper(
        firm_id, create_timekeeper_payload(**overrides), ADMIN))


def add_client(firm_id, **overrides):
    return _ok("create_client", api_client.create_client(
        firm_id, create_client_payload(**overrides), ADMIN))


def add_matter(firm_id, client_id, partner_id, **overrides):
    """Create a matter as the responsible BillingPartner (entity-backed
    identity threaded through X-User-ID)."""
    return _ok("create_matter", api_client.create_matter(
        firm_id, client_id,
        create_matter_payload(responsible_partner_id=partner_id,
                              **overrides),
        make_billing_partner_headers(partner_id)))


def get_matter(matter_id, headers=None):
    return _ok("get_matter", api_client.get_matter(
        matter_id, headers or ADMIN))


# ---------------------------------------------------------------------------
# Tier 2 — fee arrangement lifecycle
# ---------------------------------------------------------------------------

def draft_arrangement(firm_id, matter_id, arrangement_type="FLAT_FEE",
                      **overrides):
    payload = {"arrangement_type": arrangement_type,
               "fiscal_year_index": TEST_DEFAULTS["FISCAL_YEAR_INDEX"]}
    payload.update(overrides)
    return _ok("create_fee_arrangement",
               api_client.create_fee_arrangement(
                   firm_id, matter_id, payload, ANALYST))


def submit_arrangement(firm_id, arrangement_id):
    return _ok("submit_fee_arrangement",
               api_client.submit_fee_arrangement(
                   firm_id, arrangement_id, ANALYST),
               expected="PENDING_APPROVAL")


def activate_arrangement(firm_id, arrangement_id, matter_id, partner_id):
    """Activate with a fresh expected_matter_version (read-then-write)."""
    matter = get_matter(matter_id)
    return _ok("activate_fee_arrangement",
               api_client.activate_fee_arrangement(
                   firm_id, arrangement_id,
                   {"expected_matter_version": matter["version"]},
                   make_billing_partner_headers(partner_id)),
               expected="ACTIVE")


def setup_active_matter(arrangement_type="FLAT_FEE", arrangement_overrides=None,
                        client_overrides=None, matter_overrides=None,
                        fiscal_year_start_month=1, with_second_partner=False,
                        phases=None):
    """Firm + partner timekeeper + client + matter + arrangement activated.

    Returns a dict with keys: firm, client, matter, arrangement, partner,
    partner2 (optional), phases (dict task_code -> phase budget).
    The matter is ACTIVE; the returned matter snapshot is refreshed after
    activation.
    """
    firm = setup_firm(fiscal_year_start_month=fiscal_year_start_month)
    partner = add_timekeeper(firm["id"], full_name="Partner One",
                             role_title="PARTNER")
    partner2 = (add_timekeeper(firm["id"], full_name="Partner Two",
                               role_title="PARTNER")
                if with_second_partner else None)
    client = add_client(firm["id"], **(client_overrides or {}))
    matter = add_matter(firm["id"], client["id"], partner["id"],
                        **(matter_overrides or {}))

    arr_kwargs = dict(arrangement_overrides or {})
    if arrangement_type == "FLAT_FEE":
        arr_kwargs.setdefault("flat_fee_cents", 100000)
    arrangement = draft_arrangement(firm["id"], matter["id"],
                                    arrangement_type, **arr_kwargs)
    submit_arrangement(firm["id"], arrangement["id"])
    arrangement = activate_arrangement(firm["id"], arrangement["id"],
                                       matter["id"], partner["id"])

    phase_map = {}
    for phase in (phases or []):
        phase_map[phase["task_code"]] = add_active_phase_budget(
            firm["id"], matter["id"], **phase)

    matter = get_matter(matter["id"])
    return {
        "firm": firm,
        "client": client,
        "matter": matter,
        "arrangement": arrangement,
        "partner": partner,
        "partner2": partner2,
        "phases": phase_map,
    }


# ---------------------------------------------------------------------------
# Tier 3 — phase budgets and time entries
# ---------------------------------------------------------------------------

def add_phase_budget(firm_id, matter_id, task_code="L110", budget=100000,
                     etc_cents=None, stage="DISCOVERY"):
    overrides = {"task_code": task_code, "original_budget_cents": budget,
                 "litigation_stage": stage}
    if etc_cents is not None:
        overrides["etc_cents"] = etc_cents
    return _ok("create_phase_budget", api_client.create_phase_budget(
        firm_id, matter_id, create_phase_budget_payload(**overrides),
        ANALYST), expected="DRAFT")


def activate_phase_budget(firm_id, phase_budget_id, as_headers=None):
    return _ok("activate_phase_budget", api_client.activate_phase_budget(
        firm_id, phase_budget_id, as_headers or ANALYST), expected="ACTIVE")


def add_active_phase_budget(firm_id, matter_id, task_code="L110",
                            budget=100000, etc_cents=None,
                            stage="DISCOVERY"):
    phase = add_phase_budget(firm_id, matter_id, task_code=task_code,
                             budget=budget, etc_cents=etc_cents, stage=stage)
    return activate_phase_budget(firm_id, phase["id"])


def add_time_entry(firm_id, matter_id, timekeeper_id, amount_cents,
                   task_code="L110", entry_date=None, stage="DISCOVERY"):
    """Create a DRAFT entry whose billable amount is exactly amount_cents
    (1000 milli-hours at amount_cents per hour)."""
    return _ok("create_time_entry", api_client.create_time_entry(
        firm_id, matter_id,
        create_time_entry_payload(
            timekeeper_id=timekeeper_id, task_code=task_code,
            litigation_stage=stage, hours_worked_milli=1000,
            hourly_rate_cents=amount_cents,
            entry_date=entry_date or TEST_DEFAULTS["ENTRY_DATE"]),
        make_timekeeper_headers(timekeeper_id)), expected="DRAFT")


def submit_entry(firm_id, entry_id, partner_id):
    return _ok("submit_time_entry", api_client.submit_time_entry(
        firm_id, entry_id, make_billing_partner_headers(partner_id)),
        expected="SUBMITTED")


def approve_entry(firm_id, entry_id, partner_id):
    return _ok("approve_time_entry", api_client.approve_time_entry(
        firm_id, entry_id, make_billing_partner_headers(partner_id)),
        expected="APPROVED")


def bill_entry(firm_id, entry_id, partner_id):
    return _ok("mark_time_entry_billed",
               api_client.mark_time_entry_billed(
                   firm_id, entry_id,
                   make_billing_partner_headers(partner_id)),
               expected="BILLED")


def add_approved_entry(firm_id, matter_id, timekeeper_id, amount_cents,
                       partner_id, **kwargs):
    entry = add_time_entry(firm_id, matter_id, timekeeper_id, amount_cents,
                           **kwargs)
    submit_entry(firm_id, entry["id"], partner_id)
    return approve_entry(firm_id, entry["id"], partner_id)


def add_billed_entry(firm_id, matter_id, timekeeper_id, amount_cents,
                     partner_id, **kwargs):
    entry = add_approved_entry(firm_id, matter_id, timekeeper_id,
                               amount_cents, partner_id, **kwargs)
    return bill_entry(firm_id, entry["id"], partner_id)


# ---------------------------------------------------------------------------
# Tier 4 — write-downs and amendments
# ---------------------------------------------------------------------------

def create_write_down(firm_id, matter_id, entry_ids, amount_cents,
                      requester_id, reason_code="CLIENT_RELATIONS"):
    return _ok("create_write_down_request",
               api_client.create_write_down_request(
                   firm_id, matter_id,
                   create_write_down_request_payload(
                       entry_ids, amount_cents, reason_code=reason_code),
                   make_billing_partner_headers(requester_id)),
               expected="DRAFT")


def submit_write_down(firm_id, request_id, requester_id):
    return _ok("submit_write_down_request",
               api_client.submit_write_down_request(
                   firm_id, request_id,
                   make_billing_partner_headers(requester_id)))


def decide_write_down(firm_id, request_id, decision, decider_id,
                      managing=False):
    headers = (make_managing_partner_headers(decider_id) if managing
               else make_billing_partner_headers(decider_id))
    return _ok("decide_write_down_request",
               api_client.decide_write_down_request(
                   firm_id, request_id, {"decision": decision}, headers))


def apply_write_down(firm_id, request_id, applier_id, managing=False):
    headers = (make_managing_partner_headers(applier_id) if managing
               else make_billing_partner_headers(applier_id))
    return _ok("apply_write_down_request",
               api_client.apply_write_down_request(
                   firm_id, request_id, headers), expected="APPLIED")


def apply_approved_write_down(firm_id, matter_id, entry_ids, amount_cents,
                              requester_id, decider_id):
    """Full write-down walk: DRAFT -> submit -> APPROVE -> APPLIED.

    requester_id and decider_id must differ (segregation of duties).
    Returns the APPLIED WriteDownRequest.
    """
    wdr = create_write_down(firm_id, matter_id, entry_ids, amount_cents,
                            requester_id)
    submit_write_down(firm_id, wdr["id"], requester_id)
    decide_write_down(firm_id, wdr["id"], "APPROVE", decider_id)
    return apply_write_down(firm_id, wdr["id"], decider_id)


def create_amendment(firm_id, matter_id, phase_budget_id, delta_cents,
                     reason="scope change", supersedes_amendment_id=None,
                     as_headers=None):
    payload = create_budget_amendment_payload(
        phase_budget_id, delta_cents, scope_change_reason=reason,
        **({"supersedes_amendment_id": supersedes_amendment_id}
           if supersedes_amendment_id else {}))
    return _ok("create_budget_amendment",
               api_client.create_budget_amendment(
                   firm_id, matter_id, payload, as_headers or ANALYST),
               expected="DRAFT")


def submit_amendment(firm_id, amendment_id, as_headers=None):
    return _ok("submit_budget_amendment",
               api_client.submit_budget_amendment(
                   firm_id, amendment_id, as_headers or ANALYST),
               expected="PENDING_REVIEW")


def decide_amendment(firm_id, amendment_id, matter_id, decision, decider_id,
                     managing=False, expected_matter_version=None):
    """Decide an amendment with OCC. When expected_matter_version is not
    given, the current matter version is read fresh (read-then-write)."""
    if expected_matter_version is None:
        expected_matter_version = get_matter(matter_id)["version"]
    headers = (make_managing_partner_headers(decider_id) if managing
               else make_billing_partner_headers(decider_id))
    return _ok("decide_budget_amendment",
               api_client.decide_budget_amendment(
                   firm_id, amendment_id,
                   {"decision": decision,
                    "expected_matter_version": expected_matter_version},
                   headers))


def approve_amendment(firm_id, amendment_id, matter_id, decider_id,
                      managing=False):
    return decide_amendment(firm_id, amendment_id, matter_id, "APPROVE",
                            decider_id, managing=managing)


def create_submitted_amendment(firm_id, matter_id, phase_budget_id,
                               delta_cents, **kwargs):
    amd = create_amendment(firm_id, matter_id, phase_budget_id, delta_cents,
                           **kwargs)
    submit_amendment(firm_id, amd["id"])
    return amd


# ---------------------------------------------------------------------------
# Tier 5 — fiscal calendar, accrual reports, collar true-up
# ---------------------------------------------------------------------------

def advance_periods(firm_id, n=1):
    firm = None
    for _ in range(n):
        firm = _ok("advance_period", api_client.advance_period(firm_id,
                                                               ADMIN))
    return firm


def close_books(firm_id, as_headers=None):
    return _ok("close_books", api_client.close_books(
        firm_id, as_headers or ADMIN))


def latest_accrual_report(firm_id, matter_id, headers=None):
    """Fetch the matter's most recently generated accrual report."""
    data = get_success_data(api_client.list_matter_accrual_reports(
        matter_id, headers or ADMIN))
    assert isinstance(data, list) and len(data) >= 1, (
        "Setup failed: expected at least one accrual report for the matter")
    return data[-1]


def setup_matter_with_accrual_report(**kwargs):
    """Active matter under an accrual-reporting client, advanced one period
    so a fresh DRAFT accrual report exists. Returns the context dict with an
    extra 'report' key."""
    client_overrides = dict(kwargs.pop("client_overrides", {}) or {})
    client_overrides["accrual_reporting_required"] = True
    ctx = setup_active_matter(client_overrides=client_overrides, **kwargs)
    advance_periods(ctx["firm"]["id"], 1)
    ctx["report"] = latest_accrual_report(ctx["firm"]["id"],
                                          ctx["matter"]["id"])
    return ctx


def setup_collar_matter_year_ended(billed_amounts=(), lb=100000, ub=200000,
                                   share_bp=5000, phase_budget=1000000):
    """COLLAR matter (fiscal_year_index 2026) with optional BILLED entries in
    fiscal year 2026; clock then moved past fiscal year end and one period
    advanced so the arrangement is eligible for year-end true-up.

    Returns the context dict (see setup_active_matter).
    """
    ctx = setup_active_matter(
        arrangement_type="COLLAR",
        arrangement_overrides={
            "collar_lower_bound_cents": lb,
            "collar_upper_bound_cents": ub,
            "collar_share_pct_bp": share_bp,
            "fiscal_year_index": TEST_DEFAULTS["FISCAL_YEAR_INDEX"],
        },
        phases=([{"task_code": "L110", "budget": phase_budget}]
                if billed_amounts else None),
    )
    for amount in billed_amounts:
        add_billed_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                         ctx["partner"]["id"], amount, ctx["partner"]["id"])
    set_clock(AFTER_YEAR_END_CLOCK)
    advance_periods(ctx["firm"]["id"], 1)
    ctx["matter"] = get_matter(ctx["matter"]["id"])
    return ctx


def run_true_up(firm_id, matter_id, partner_id):
    return _ok("run_year_end_collar_true_up",
               api_client.run_year_end_collar_true_up(
                   firm_id, matter_id,
                   make_billing_partner_headers(partner_id)),
               expected="COMPUTED")


def advance_and_close_books(firm_id, cycles=1):
    """Advance one period then close the books, `cycles` times. Returns the
    firm snapshot from the last close."""
    firm = None
    for _ in range(cycles):
        advance_periods(firm_id, 1)
        firm = close_books(firm_id)
    return firm
