"""Composite setup helpers.

The harness restarts the server before every test, so every test starts
against an empty database; these helpers build complete precondition chains
out of PRD-declared endpoints only. Setup calls use get_success_data() so a
broken precondition surfaces as a clear "Setup step failed" message.

Identity threading: the Applicant role is entity-backed by Customer. Every
account context carries applicant headers built from the real customer id via
make_applicant_headers(); ownership-gated calls never use the shared constant.

Document rule (PRD §3.3): a COMPLETE decision requires one ACCEPTED document
of EACH of the three types, so the happy-path chains upload and accept
SITE_PLAN, SINGLE_LINE_DIAGRAM, and INSURANCE_CERTIFICATE.
"""
from prd_bench_local_runner.testing import build_user_headers, get_success_data

from .api_client import api_client
from .assertions import parse_instant
from .factories import (
    create_application_payload,
    create_cost_estimate_payload,
    create_customer_payload,
    create_document_payload,
    create_feeder_payload,
    create_inspection_payload,
    create_meter_exchange_payload,
    create_meter_reading_payload,
    create_program_payload,
    create_service_account_payload,
    create_service_transformer_payload,
    create_supplemental_review_payload,
    create_tariff_schedule_payload,
    record_inspection_result_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_inspector_headers,
)

ADMIN = TEST_USERS["program_administrator_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]

# Default field-work instants (the default logical clock is
# 2026-08-01T00:00:00Z; inspections are recorded after the clock advances).
DEFAULT_EXCHANGE_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T11:00:00Z")
TRUE_UP_RUN_INSTANT = "2027-04-15T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_program(name="P", **overrides):
    payload = create_program_payload(name=name, **overrides)
    return get_success_data(api_client.create_program(payload, ADMIN))


def create_tariff(program_id, **overrides):
    payload = create_tariff_schedule_payload(program_id, **overrides)
    return get_success_data(api_client.create_tariff_schedule(payload, ADMIN))


def create_feeder(code="F-1", **overrides):
    payload = create_feeder_payload(feeder_code=code, **overrides)
    return get_success_data(api_client.create_feeder(payload, ADMIN))


def create_transformer(feeder_id, code="T-1", **overrides):
    payload = create_service_transformer_payload(feeder_id,
                                                 transformer_code=code,
                                                 **overrides)
    return get_success_data(api_client.create_service_transformer(payload,
                                                                  ADMIN))


def create_customer(name="Cust", email="cust@example.com"):
    payload = create_customer_payload(full_name=name, email=email)
    return get_success_data(api_client.create_customer(payload, ADMIN))


def create_service_account(customer_id, transformer_id,
                           account_number="ACCT-1", **overrides):
    payload = create_service_account_payload(
        customer_id, transformer_id, account_number=account_number,
        **overrides)
    return get_success_data(api_client.create_service_account(payload, ADMIN))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: program + grid topology + tariff scenario
# ---------------------------------------------------------------------------

def setup_program_with_grid(name, with_tariff=True, program_overrides=None,
                            tariff_overrides=None, feeder_overrides=None,
                            transformer_overrides=None):
    """Program + feeder + transformer (+ open-ended standard tariff).

    Returns a scenario dict. Numeric defaults keep every screen comfortably
    green for a 10 kW application: transformer limit 5,000,000 W, feeder
    limit 1,500,000 W, no pre-existing DER.
    """
    program = create_program(name, **(program_overrides or {}))
    tariff = None
    if with_tariff:
        tariff = create_tariff(program["id"], schedule_code=f"{name}-2026",
                               **(tariff_overrides or {}))
    feeder = create_feeder(f"F-{name}", **(feeder_overrides or {}))
    transformer = create_transformer(feeder["id"], f"T-{name}",
                                     **(transformer_overrides or {}))
    return {
        "name": name,
        "program": program,
        "tariff": tariff,
        "feeder": feeder,
        "transformer": transformer,
    }


def add_customer_account(sc, suffix="1", service_class="COMMERCIAL",
                         prior_annual_usage_wh=20_000_000, transformer=None):
    """Customer + service account on the scenario transformer. Returns a
    context dict whose applicant headers carry the real customer id."""
    customer = create_customer(f"{sc['name']} Cust {suffix}",
                               f"{sc['name'].lower()}-{suffix}@example.com")
    account = create_service_account(
        customer["id"], (transformer or sc["transformer"])["id"],
        account_number=f"{sc['name']}-{suffix}",
        service_class=service_class,
        prior_annual_usage_wh=prior_annual_usage_wh)
    return {
        "customer": customer,
        "account": account,
        "applicant": make_applicant_headers(customer["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 3: application intake chains
# ---------------------------------------------------------------------------

def create_draft_application(sc, ctx, size=10_000, production=15_000_000,
                             technology="SOLAR_PV"):
    payload = create_application_payload(
        ctx["account"]["id"], sc["program"]["id"], technology=technology,
        system_size_watts_ac=size, estimated_annual_production_wh=production)
    return get_success_data(
        api_client.create_application(payload, ctx["applicant"]))


def upload_required_documents(ctx, application_id):
    """Upload one document of each of the three required types."""
    docs = {}
    for doc_type, title in (
            ("SITE_PLAN", "site plan"),
            ("SINGLE_LINE_DIAGRAM", "single line diagram"),
            ("INSURANCE_CERTIFICATE", "certificate of insurance")):
        docs[doc_type] = get_success_data(api_client.create_document(
            create_document_payload(application_id, doc_type=doc_type,
                                    title=title), ctx["applicant"]))
    return docs


def accept_documents(docs):
    for doc in docs.values():
        get_success_data(api_client.review_document(
            doc["id"], {"outcome": "ACCEPTED"}, COORDINATOR))


def submit_application(app_id, ctx):
    return get_success_data(
        api_client.submit_application(app_id, ctx["applicant"]))


def decide_completeness(app_id, outcome="COMPLETE", deficiency_note=None):
    payload = {"outcome": outcome}
    if deficiency_note is not None:
        payload["deficiency_note"] = deficiency_note
    return get_success_data(
        api_client.completeness_decision(app_id, payload, COORDINATOR))


def drive_to_capacity_reserved(sc, ctx, size=10_000, production=15_000_000,
                               technology="SOLAR_PV"):
    """Draft -> documents accepted -> submit -> COMPLETE -> CAPACITY_RESERVED.

    Requires the program to have at least `size` watts of headroom and the
    design to pass eligibility. Returns the application.
    """
    app = create_draft_application(sc, ctx, size=size, production=production,
                                   technology=technology)
    accept_documents(upload_required_documents(ctx, app["id"]))
    submit_application(app["id"], ctx)
    app = decide_completeness(app["id"], "COMPLETE")
    assert app["application_status"] == "CAPACITY_RESERVED", (
        f"Setup expected CAPACITY_RESERVED, got {app['application_status']}")
    return app


def drive_to_screen_passed(sc, ctx, size=10_000, production=15_000_000,
                           technology="SOLAR_PV"):
    """CAPACITY_RESERVED -> all screens pass -> SCREEN_PASSED."""
    app = drive_to_capacity_reserved(sc, ctx, size=size,
                                     production=production,
                                     technology=technology)
    report = get_success_data(api_client.create_screening_report(
        {"application_id": app["id"]}, ENGINEER))
    assert report["outcome"] == "PASSED", (
        f"Setup expected a passing screen, got {report['outcome']} "
        f"{report['failing_screens']}")
    app = get_success_data(api_client.get_application(app["id"], ADMIN))
    assert app["application_status"] == "SCREEN_PASSED"
    return app


def drive_to_supplemental_review(sc, ctx, size=20_000, production=30_000_000,
                                 technology="SOLAR_PV"):
    """CAPACITY_RESERVED -> some screen fails -> SUPPLEMENTAL_REVIEW.

    Caller is responsible for grid geometry that fails a screen for `size`.
    Returns (application, report).
    """
    app = drive_to_capacity_reserved(sc, ctx, size=size,
                                     production=production,
                                     technology=technology)
    report = get_success_data(api_client.create_screening_report(
        {"application_id": app["id"]}, ENGINEER))
    assert report["outcome"] == "FAILED", (
        f"Setup expected a failing screen, got {report['outcome']}")
    app = get_success_data(api_client.get_application(app["id"], ADMIN))
    assert app["application_status"] == "SUPPLEMENTAL_REVIEW"
    return app, report


def drive_to_awaiting_cost_estimate(sc, ctx, size=20_000,
                                    production=30_000_000,
                                    technology="SOLAR_PV",
                                    review_type="FACILITIES_STUDY",
                                    findings=None):
    """SUPPLEMENTAL_REVIEW -> review completed UPGRADES_REQUIRED ->
    AWAITING_COST_ESTIMATE. Returns (application, report, review)."""
    app, report = drive_to_supplemental_review(
        sc, ctx, size=size, production=production, technology=technology)
    payload = {"outcome": "UPGRADES_REQUIRED"}
    if findings is not None:
        payload["findings"] = findings
    review = get_success_data(api_client.create_supplemental_review(
        create_supplemental_review_payload(app["id"],
                                           review_type=review_type),
        ENGINEER))
    review = get_success_data(api_client.complete_supplemental_review(
        review["id"], payload, ENGINEER))
    assert review["outcome"] == "UPGRADES_REQUIRED"
    app = get_success_data(api_client.get_application(app["id"], ADMIN))
    assert app["application_status"] == "AWAITING_COST_ESTIMATE"
    return app, report, review


def issue_estimate(sc, app, review, items=None, contingency_pct=10):
    """Issue a cost estimate, threading the application's current version
    (the OCC check of PRD §2.9). Returns (estimate, application)."""
    fresh = get_success_data(api_client.get_application(app["id"], ADMIN))
    payload = create_cost_estimate_payload(
        app["id"], review["id"], fresh["version"],
        items=items or [{"description": "Upgrade work", "amount_cents": 50_000}],
        contingency_pct=contingency_pct)
    estimate = get_success_data(api_client.create_cost_estimate(payload,
                                                                ENGINEER))
    app = get_success_data(api_client.get_application(app["id"], ADMIN))
    return estimate, app


def drive_to_customer_decision_pending(sc, ctx, size=20_000,
                                       production=30_000_000,
                                       items=None, contingency_pct=10):
    """Full chain through estimate issuance -> CUSTOMER_DECISION_PENDING.
    Returns (application, review, estimate)."""
    app, _report, review = drive_to_awaiting_cost_estimate(
        sc, ctx, size=size, production=production)
    estimate, app = issue_estimate(sc, app, review, items=items,
                                   contingency_pct=contingency_pct)
    assert app["application_status"] == "CUSTOMER_DECISION_PENDING"
    assert estimate["estimate_status"] == "ISSUED"
    return app, review, estimate


# ---------------------------------------------------------------------------
# Tier 4: field work, PTO, and operating accounts
# ---------------------------------------------------------------------------

def schedule_and_complete_exchange(app_id, crew_id="crew-1",
                                   window=DEFAULT_EXCHANGE_WINDOW,
                                   technician_id="tech-1",
                                   meter_serial="MTR-1"):
    """Schedule a meter exchange and complete it. Returns the exchange."""
    exchange = get_success_data(api_client.create_meter_exchange(
        create_meter_exchange_payload(app_id, crew_id=crew_id,
                                      window_start=window[0],
                                      window_end=window[1]), TECHNICIAN))
    return get_success_data(api_client.complete_meter_exchange(
        exchange["id"], meter_serial,
        # technician_user_id is recorded from X-User-ID.
        build_user_headers(technician_id, "MeterTechnician")))


def _fmt_instant(dt):
    """Render a UTC datetime as ISO 8601 with a Z suffix (whole seconds)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def schedule_and_pass_inspection(ctx, app_id,
                                 scheduled_date=None,
                                 occurred_at=None,
                                 clock=None,
                                 inspector_id="insp-1"):
    """Request an inspection, advance the clock, record a PASSED result.

    Timing defaults are relative to the CURRENT logical clock, so the chain
    stays valid no matter how far a scenario has already advanced it (PRD
    3.7 rejects a scheduled_date earlier than the current clock time): the
    inspection is scheduled now + 4 days 9 hours, the result is recorded one
    hour after that, and the clock advances to now + 5 days, keeping
    occurred_at inside [scheduled_date, now]. From the default clock
    (2026-08-01T00:00:00Z) this reproduces the classic absolute instants
    2026-08-05T09:00 / 2026-08-05T10:00 / 2026-08-06T00:00 exactly.
    """
    if scheduled_date is None or occurred_at is None or clock is None:
        import datetime
        now = parse_instant(get_success_data(
            api_client.get_clock(ADMIN))["current_utc"])
        if scheduled_date is None:
            scheduled_date = _fmt_instant(
                now + datetime.timedelta(days=4, hours=9))
        if occurred_at is None:
            occurred_at = _fmt_instant(
                parse_instant(scheduled_date) + datetime.timedelta(hours=1))
        if clock is None:
            clock = _fmt_instant(now + datetime.timedelta(days=5))
    inspection = get_success_data(api_client.create_inspection(
        create_inspection_payload(app_id, scheduled_date=scheduled_date),
        ctx["applicant"]))
    set_clock(clock)
    inspection = get_success_data(api_client.record_inspection_result(
        inspection["id"],
        record_inspection_result_payload(outcome="PASSED",
                                         occurred_at=occurred_at),
        make_inspector_headers(inspector_id)))
    assert inspection["inspection_status"] == "RESULT_RECORDED"
    assert inspection["outcome"] == "PASSED"
    return inspection


def drive_to_pto_granted(sc, ctx, size=10_000, production=15_000_000,
                         technology="SOLAR_PV", crew_id="crew-1",
                         technician_id="tech-1", inspector_id="insp-1",
                         meter_serial="MTR-1"):
    """SCREEN_PASSED -> exchange COMPLETED -> inspection PASSED -> PTO_GRANTED.
    Returns a dict of the application, exchange, and inspection."""
    app = drive_to_screen_passed(sc, ctx, size=size, production=production,
                                 technology=technology)
    exchange = schedule_and_complete_exchange(
        app["id"], crew_id=crew_id, technician_id=technician_id,
        meter_serial=meter_serial)
    inspection = schedule_and_pass_inspection(ctx, app["id"],
                                              inspector_id=inspector_id)
    app = get_success_data(api_client.grant_pto(app["id"], COORDINATOR))
    assert app["application_status"] == "PTO_GRANTED"
    return {"app": app, "exchange": exchange, "inspection": inspection}


def post_reading(account_id, period_start, period_end, import_wh, export_wh):
    """Post a meter reading, threading the account's current version (the OCC
    check of PRD §2.9). Returns the created reading."""
    account = get_success_data(api_client.get_service_account(account_id,
                                                              ADMIN))
    payload = create_meter_reading_payload(
        account_id, account["version"], period_start=period_start,
        period_end=period_end, import_wh=import_wh, export_wh=export_wh)
    return get_success_data(api_client.create_meter_reading(payload,
                                                            TECHNICIAN))


def drive_to_operating(sc, ctx, size=10_000, production=15_000_000,
                       technology="SOLAR_PV", first_reading=None):
    """PTO_GRANTED -> first reading posts -> OPERATING.

    first_reading defaults to a surplus August period (import 500000,
    export 800000). Returns the field-work dict plus the reading."""
    result = drive_to_pto_granted(sc, ctx, size=size, production=production,
                                  technology=technology)
    reading_spec = first_reading or {}
    reading = post_reading(
        ctx["account"]["id"],
        reading_spec.get("period_start", "2026-08-01T00:00:00Z"),
        reading_spec.get("period_end", "2026-09-01T00:00:00Z"),
        reading_spec.get("import_wh", 500_000),
        reading_spec.get("export_wh", 800_000))
    app = get_success_data(api_client.get_application(result["app"]["id"],
                                                      ADMIN))
    assert app["application_status"] == "OPERATING"
    result["app"] = app
    result["reading"] = reading
    return result


def get_application(app_id):
    return get_success_data(api_client.get_application(app_id, ADMIN))


def get_account(account_id):
    return get_success_data(api_client.get_service_account(account_id, ADMIN))


def get_program(program_id):
    return get_success_data(api_client.get_program(program_id, ADMIN))


def get_feeder(feeder_id):
    return get_success_data(api_client.get_feeder(feeder_id, ADMIN))


def get_transformer(transformer_id):
    return get_success_data(
        api_client.get_service_transformer(transformer_id, ADMIN))


def list_ledger_entries(account_id=None, **filters):
    params = dict(filters)
    if account_id is not None:
        params["service_account_id"] = account_id
    resp = api_client.list_ledger_entries(ADMIN, params=params or None)
    data = get_success_data(resp)
    return data
