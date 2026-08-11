"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so each fixture builds its preconditions from scratch using
only PRD-declared endpoints. Setup calls use the lenient get_success_data()
validator so failures surface as clear setup errors.

Ownership threading: the Landlord role is entity_backed — every
ownership-gated call uses make_landlord_headers(landlord["id"]).

The canonical timeline used by the full-pipeline fixtures (CA):
  2026-05-02T08:00:00Z  notice served (PAY_OR_QUIT, CA cure 3 days)
  2026-05-06T00:00:01Z  past the 2026-05-05T23:59:59Z cure deadline -> ops run
                        expires the notice -> case NOTICE_EXPIRED
  package prepared + paid + ACCEPTED (clerk-a) -> case FILED
  2026-06-01T11:00:00Z  clock; service SERVED at 2026-06-01T10:00:00Z
                        -> case SERVICE_COMPLETE
  hearing CR-1 2026-06-15T10:00-10:30 (exactly the CA 10-day lead
                        from service date 2026-06-01... satisfied)
  hearing concluded -> case HEARING_CONCLUDED
  2026-06-20T12:00:00Z  judgment entered by clerk-b (SOD) -> JUDGMENT_ENTERED
  2026-06-25T12:00:00Z  ops run at exactly appeal_deadline -> FINAL
  writ requested (fee 4000) + issued -> case WRIT_ISSUED
  lockout scheduled for dep-1 2026-06-26T09:00-10:00 -> LOCKOUT_SCHEDULED

  (The lockout window is kept one day after issuance: PRD 3.7 pins the RULE
  "window_end no later than expires_on" and defines expires_on as issued_at
  plus "the jurisdiction's writ validity period", but never states the
  period's length — so fixtures must schedule windows that satisfy the rule
  under any plausible validity period.)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, WRIT_FEE
from .factories import (
    compute_filing_fee_cents,
    create_answer_payload,
    create_case_payload,
    create_filing_package_payload,
    create_hearing_payload,
    create_judgment_payload,
    create_landlord_payload,
    create_notice_payload,
    create_referral_payload,
    create_review_payload,
    create_schedule_lockout_payload,
    create_service_attempt_payload,
    create_tenancy_payload,
    create_unit_payload,
    create_writ_payload,
)
from .test_users import (
    make_admin_headers,
    make_clerk_headers,
    make_deputy_headers,
    make_landlord_headers,
    make_mediator_headers,
    make_process_server_headers,
)

ADMIN = make_admin_headers("test-admin-1")
CLERK_A = make_clerk_headers(TEST_DEFAULTS["CLERK_A"])
CLERK_B = make_clerk_headers(TEST_DEFAULTS["CLERK_B"])
PS1 = make_process_server_headers(TEST_DEFAULTS["PROCESS_SERVER"])


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_ops():
    return get_success_data(api_client.run_ops(CLERK_A))


def create_landlord(**overrides):
    data = get_success_data(
        api_client.create_landlord(create_landlord_payload(**overrides), ADMIN)
    )
    return data


def create_unit(landlord, jurisdiction_code="CA", **overrides):
    ll = make_landlord_headers(landlord["id"])
    return get_success_data(
        api_client.create_unit(
            create_unit_payload(landlord["id"], jurisdiction_code, **overrides), ll
        )
    )


def create_tenancy(landlord, unit, **overrides):
    ll = make_landlord_headers(landlord["id"])
    return get_success_data(
        api_client.create_tenancy(create_tenancy_payload(unit["id"], **overrides), ll)
    )


def create_case(landlord, tenancy, case_reason="NONPAYMENT"):
    ll = make_landlord_headers(landlord["id"])
    return get_success_data(
        api_client.create_case(create_case_payload(tenancy["id"], case_reason), ll)
    )


def create_notice(landlord, case, notice_type="PAY_OR_QUIT", **overrides):
    """Create a notice against the case at its CURRENT version."""
    ll = make_landlord_headers(landlord["id"])
    current = get_success_data(api_client.get_case(case["id"], CLERK_A))
    payload = create_notice_payload(current["version"], notice_type, **overrides)
    notice = get_success_data(api_client.create_notice(case["id"], payload, ll))
    return notice


def setup_case_draft(jurisdiction_code="CA", case_reason="NONPAYMENT"):
    """Landlord + unit + tenancy + DRAFT case. Returns dict of entities."""
    landlord = create_landlord()
    unit = create_unit(landlord, jurisdiction_code)
    tenancy = create_tenancy(landlord, unit)
    case = create_case(landlord, tenancy, case_reason)
    return {
        "landlord": landlord,
        "unit": unit,
        "tenancy": tenancy,
        "case": case,
        "jurisdiction": jurisdiction_code,
    }


def setup_case_notice_active(jurisdiction_code="CA", case_reason="NONPAYMENT",
                             notice_type=None, served_on="2026-05-02",
                             clock_before_notice="2026-05-02T08:00:00Z",
                             **notice_overrides):
    """DRAFT case + one PENDING notice; case NOTICE_ACTIVE."""
    ctx = setup_case_draft(jurisdiction_code, case_reason)
    if notice_type is None:
        notice_type = {
            "NONPAYMENT": "PAY_OR_QUIT",
            "LEASE_VIOLATION": "CURE_OR_QUIT",
            "SEVERE": "UNCONDITIONAL_QUIT",
        }[case_reason]
    set_clock(clock_before_notice)
    ctx["notice"] = create_notice(
        ctx["landlord"], ctx["case"], notice_type, served_on=served_on,
        **notice_overrides,
    )
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return ctx


def setup_case_notice_expired(jurisdiction_code="CA", case_reason="NONPAYMENT",
                              notice_type=None, served_on="2026-05-02",
                              expire_clock="2026-05-06T00:00:01Z",
                              **notice_overrides):
    """Notice expired by an ops run; case NOTICE_EXPIRED.

    Default timeline serves a CA PAY_OR_QUIT on 2026-05-02 (3-day cure,
    deadline 2026-05-05T23:59:59Z) and sweeps at 2026-05-06T00:00:01Z.
    """
    ctx = setup_case_notice_active(
        jurisdiction_code, case_reason, notice_type, served_on=served_on,
        **notice_overrides,
    )
    set_clock(expire_clock)
    run_ops()
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    ctx["notice"] = get_success_data(
        api_client.get_notice(ctx["notice"]["id"], CLERK_A)
    )
    return ctx


def prepare_package(ctx, claimed_amount_cents=None, defendant_names=None,
                    jury_demanded=False, efiled=False, pay=True):
    """Create a DRAFT filing package on the context's case; optionally pay the
    full computed fee. Returns the package (refreshed)."""
    landlord = ctx["landlord"]
    ll = make_landlord_headers(landlord["id"])
    if claimed_amount_cents is None:
        claimed_amount_cents = TEST_DEFAULTS["CLAIMED_AMOUNT_CENTS"]
    if defendant_names is None:
        defendant_names = [TEST_DEFAULTS["DEFENDANT_NAME"]]
    payload = create_filing_package_payload(
        claimed_amount_cents=claimed_amount_cents,
        defendant_names=defendant_names,
        jury_demanded=jury_demanded,
        efiled=efiled,
    )
    package = get_success_data(
        api_client.create_filing_package(ctx["case"]["id"], payload, ll)
    )
    if pay:
        fee = package["filing_fee_cents"]
        package = get_success_data(
            api_client.record_fee_payment(
                package["id"], {"amount_cents": fee}, ll
            )
        )
    return package


def review_package(package, decision="ACCEPT", clerk_headers=None, **overrides):
    hdrs = clerk_headers or CLERK_A
    return get_success_data(
        api_client.review_filing_package(
            package["id"], create_review_payload(decision, **overrides), hdrs
        )
    )


def setup_case_filed(jurisdiction_code="CA", defendant_names=None,
                     claimed_amount_cents=None):
    """Case FILED: package prepared, fully paid, and ACCEPTED by clerk-a."""
    ctx = setup_case_notice_expired(jurisdiction_code)
    package = prepare_package(
        ctx, claimed_amount_cents=claimed_amount_cents,
        defendant_names=defendant_names,
    )
    package = review_package(package, "ACCEPT", CLERK_A)
    ctx["package"] = package
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return ctx


def serve_all_defendants(ctx, served_at="2026-06-01T10:00:00Z",
                         clock="2026-06-01T11:00:00Z", server_headers=None):
    """Record a SERVED attempt for every defendant of the ACCEPTED package."""
    hdrs = server_headers or PS1
    set_clock(clock)
    attempts = []
    for name in ctx["package"]["defendant_names"]:
        attempt = get_success_data(
            api_client.create_service_attempt(
                ctx["case"]["id"],
                create_service_attempt_payload(
                    defendant_name=name, served_at=served_at
                ),
                hdrs,
            )
        )
        attempts.append(attempt)
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return attempts


def setup_case_service_complete(jurisdiction_code="CA", defendant_names=None,
                                served_at="2026-06-01T10:00:00Z"):
    """Case SERVICE_COMPLETE with service_completed_at == served_at."""
    ctx = setup_case_filed(jurisdiction_code, defendant_names=defendant_names)
    serve_all_defendants(ctx, served_at=served_at)
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return ctx


def schedule_hearing(ctx, courtroom=None, start_at="2026-06-15T10:00:00Z",
                     end_at="2026-06-15T10:30:00Z", clerk_headers=None):
    hdrs = clerk_headers or CLERK_A
    payload = create_hearing_payload(
        courtroom=courtroom or TEST_DEFAULTS["COURTROOM"],
        start_at=start_at, end_at=end_at,
    )
    hearing = get_success_data(
        api_client.create_hearing(ctx["case"]["id"], payload, hdrs)
    )
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return hearing


def setup_case_hearing_scheduled(jurisdiction_code="CA", **hearing_kw):
    """Case HEARING_SCHEDULED with a SCHEDULED hearing (CR-1 by default)."""
    ctx = setup_case_service_complete(jurisdiction_code)
    ctx["hearing"] = schedule_hearing(ctx, **hearing_kw)
    return ctx


def setup_case_answered_with_referral(defense_codes=None, mediator_id=None):
    """Case MEDIATION_PENDING: answer (mediation_requested=True) + PENDING
    referral; the SCHEDULED hearing is STAYED."""
    ctx = setup_case_hearing_scheduled("CA")
    answer = get_success_data(
        api_client.create_answer(
            ctx["case"]["id"],
            create_answer_payload(defense_codes=defense_codes or ["HABITABILITY"]),
            CLERK_A,
        )
    )
    referral = get_success_data(
        api_client.create_mediation_referral(
            answer["id"],
            create_referral_payload(mediator_id=mediator_id or TEST_DEFAULTS["MEDIATOR"]),
            CLERK_A,
        )
    )
    ctx["answer"] = answer
    ctx["referral"] = referral
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return ctx


def setup_case_hearing_concluded(jurisdiction_code="CA"):
    """Case HEARING_CONCLUDED (hearing HELD); clock at 2026-06-20T12:00:00Z,
    ready for judgment entry."""
    ctx = setup_case_hearing_scheduled(jurisdiction_code)
    get_success_data(api_client.conclude_hearing(ctx["hearing"]["id"], {}, CLERK_A))
    set_clock("2026-06-20T12:00:00Z")
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return ctx


def enter_judgment(ctx, clerk_headers=None, **overrides):
    """Enter the judgment. Defaults to clerk-b so the SOD rule vs clerk-a's
    package acceptance is satisfied."""
    hdrs = clerk_headers or CLERK_B
    judgment = get_success_data(
        api_client.enter_judgment(
            ctx["case"]["id"], create_judgment_payload(**overrides), hdrs
        )
    )
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return judgment


def setup_judgment_entered(jurisdiction_code="CA", **judgment_overrides):
    """Judgment ENTERED at 2026-06-20T12:00:00Z by clerk-b."""
    ctx = setup_case_hearing_concluded(jurisdiction_code)
    ctx["judgment"] = enter_judgment(ctx, **judgment_overrides)
    return ctx


def finalize_judgment(ctx, clock="2026-06-25T12:00:00Z"):
    """Advance to the appeal deadline (CA: entered 2026-06-20 + 5 days) and
    run the ops sweep so the judgment flips ENTERED -> FINAL. The default
    clock lands exactly on the CA appeal_deadline (>= boundary finalizes)."""
    set_clock(clock)
    summary = run_ops()
    ctx["judgment"] = get_success_data(
        api_client.get_judgment(ctx["judgment"]["id"], CLERK_A)
    )
    return summary


def setup_judgment_final(jurisdiction_code="CA", **judgment_overrides):
    """Judgment FINAL (ops-run at exactly the appeal deadline)."""
    ctx = setup_judgment_entered(jurisdiction_code, **judgment_overrides)
    finalize_judgment(ctx)
    return ctx


def request_and_issue_writ(ctx, clerk_headers=None):
    """Landlord requests the writ with the exact jurisdictional fee; clerk
    issues it. Returns the ISSUED writ."""
    landlord = ctx["landlord"]
    ll = make_landlord_headers(landlord["id"])
    writ = get_success_data(
        api_client.request_writ(
            ctx["judgment"]["id"],
            create_writ_payload(ctx["jurisdiction"]),
            ll,
        )
    )
    hdrs = clerk_headers or CLERK_A
    writ = get_success_data(api_client.issue_writ(writ["id"], hdrs))
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return writ


def setup_writ_issued(jurisdiction_code="CA"):
    """FINAL judgment + ISSUED writ; case WRIT_ISSUED."""
    ctx = setup_judgment_final(jurisdiction_code)
    ctx["writ"] = request_and_issue_writ(ctx)
    return ctx


def schedule_lockout(ctx, deputy_id=None, window_start="2026-06-26T09:00:00Z",
                     window_end="2026-06-26T10:00:00Z"):
    dep = deputy_id or TEST_DEFAULTS["DEPUTY"]
    writ = get_success_data(
        api_client.schedule_lockout(
            ctx["writ"]["id"],
            create_schedule_lockout_payload(
                deputy_id=dep, window_start=window_start, window_end=window_end
            ),
            make_deputy_headers(dep),
        )
    )
    ctx["writ"] = writ
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return writ


def setup_writ_scheduled(jurisdiction_code="CA", deputy_id=None,
                         window_start="2026-06-26T09:00:00Z",
                         window_end="2026-06-26T10:00:00Z"):
    """Writ SCHEDULED for a deputy; case LOCKOUT_SCHEDULED."""
    ctx = setup_writ_issued(jurisdiction_code)
    schedule_lockout(ctx, deputy_id, window_start, window_end)
    ctx["deputy_id"] = deputy_id or TEST_DEFAULTS["DEPUTY"]
    return ctx


def setup_executed_with_storage(jurisdiction_code="CA", deputy_id=None,
                                window_start="2026-06-26T09:00:00Z",
                                window_end="2026-06-26T10:00:00Z",
                                execute_at=None, items_summary="boxes"):
    """Full pipeline through EXECUTED. Clock is set to window_start (or
    execute_at) and the assigned deputy executes. Returns the context with
    the created STORED PropertyStorageRecord attached as ctx['storage']."""
    dep = deputy_id or TEST_DEFAULTS["DEPUTY"]
    ctx = setup_writ_scheduled(jurisdiction_code, dep, window_start, window_end)
    set_clock(execute_at or window_start)
    writ = get_success_data(
        api_client.execute_writ(
            ctx["writ"]["id"], {"items_summary": items_summary},
            make_deputy_headers(dep),
        )
    )
    ctx["writ"] = writ
    records = get_success_data(
        api_client.list_writ_storage_records(writ["id"], CLERK_A)
    )
    ctx["storage"] = records[0] if isinstance(records, list) else records["data"][0]
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return ctx


def setup_two_cases_notice_expired(jurisdiction_code="CA", case_reason="NONPAYMENT"):
    """One landlord, two units/tenancies/cases, both notices expired by a
    single ops run. Returns (ctx_a, ctx_b)."""
    landlord = create_landlord()
    ctxs = []
    for label in ("A", "B"):
        unit = create_unit(landlord, jurisdiction_code, unit_label=label)
        tenancy = create_tenancy(landlord, unit, tenant_full_name=f"T {label}")
        case = create_case(landlord, tenancy, case_reason)
        ctxs.append({
            "landlord": landlord, "unit": unit, "tenancy": tenancy,
            "case": case, "jurisdiction": jurisdiction_code,
        })
    set_clock("2026-05-02T08:00:00Z")
    for ctx in ctxs:
        ctx["notice"] = create_notice(ctx["landlord"], ctx["case"])
    set_clock("2026-05-06T00:00:01Z")
    run_ops()
    for ctx in ctxs:
        ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], CLERK_A))
    return ctxs[0], ctxs[1]


def get_case(case_id):
    return get_success_data(api_client.get_case(case_id, CLERK_A))


def get_notice(notice_id):
    return get_success_data(api_client.get_notice(notice_id, CLERK_A))


def get_hearing(hearing_id):
    return get_success_data(api_client.get_hearing(hearing_id, CLERK_A))


def get_answer(answer_id):
    return get_success_data(api_client.get_answer(answer_id, CLERK_A))


def get_referral(referral_id):
    return get_success_data(api_client.get_referral(referral_id, CLERK_A))


def get_judgment(judgment_id):
    return get_success_data(api_client.get_judgment(judgment_id, CLERK_A))


def get_writ(writ_id):
    return get_success_data(api_client.get_writ(writ_id, CLERK_A))


def get_storage_record(record_id):
    return get_success_data(api_client.get_storage_record(record_id, CLERK_A))


def get_tenancy(tenancy_id):
    return get_success_data(api_client.get_tenancy(tenancy_id, CLERK_A))


def get_unit(unit_id):
    return get_success_data(api_client.get_unit(unit_id, CLERK_A))


def get_package(package_id):
    return get_success_data(api_client.get_filing_package(package_id, CLERK_A))


def get_collection_entry(entry_id):
    return get_success_data(api_client.get_collection_entry(entry_id, CLERK_A))


def get_report(report_id):
    return get_success_data(api_client.get_rental_history_report(report_id, CLERK_A))


__all__ = [name for name in dir() if not name.startswith("_")]
