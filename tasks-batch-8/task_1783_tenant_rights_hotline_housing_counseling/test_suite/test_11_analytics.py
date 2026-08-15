"""Call-volume analytics: RAW vs DEDUPLICATED views, confidentiality exclusion,
and the zero-denominator rule (PRD §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_escalation_rate,
    grant_consent,
    open_case,
    setup_call_volume_scene,
    setup_hotline,
    start_active_session,
    validate_error,
    validate_success,
    wrap_up_session,
)

ANALYST = TEST_USERS["analyst_headers"]
WINDOW = {"from_iso8601": "2026-08-01T00:00:00Z",
          "to_iso8601": "2026-08-02T00:00:00Z"}


def test_call_volume_raw_view(api):
    """PRD §3.9: "Under the default `RAW` view, `call_count` counts every eligible
    session."
    PRD §3.9: "`escalated_case_count` counts cases whose `last_escalated_at` falls
    inside the window under the same filters. The `escalation_rate` is 0 when
    `call_count` is 0, and otherwise the escalated count divided by the call count,
    rounded half-up to four decimal places; the same window and filters under the
    two views can therefore legitimately report different rates."
    PRD §3.9: "Eligible sessions are those that reached `ACTIVE` at least once
    (their `session_status` stands at `ACTIVE`, `WRAPPED_UP`, or `DROPPED`) with
    `actual_start_at` inside the window; sessions that only ever queued, and
    abandoned sessions that never started, are excluded."

    Design: Difficulty/dual_variant_calc/call_volume_raw_vs_deduplicated
    """
    setup_call_volume_scene()
    data = validate_success(api.get_call_volume(ANALYST, params={**WINDOW, "view": "RAW"}))
    assert data["view"] == "RAW"
    # Sessions: A x2, B x1, anonymous C x1, anonymous D x1 -> 5 raw.
    assert data["call_count"] == 5
    assert data["escalated_case_count"] == 1
    assert_escalation_rate(data["escalation_rate"], 0.2)  # 1/5, 4dp round-half-up


def test_call_volume_deduplicated_view(api):
    """PRD §3.9: "Under the `DEDUPLICATED` view, `call_count` counts each identified
    caller — `is_anonymous` false — once, plus one for every anonymous session,
    because anonymous callers cannot be deduplicated."
    PRD §3.9: "The `escalation_rate` is 0 when `call_count` is 0, and otherwise the
    escalated count divided by the call count, rounded half-up to four decimal
    places; the same window and filters under the two views can therefore
    legitimately report different rates."

    Design: Difficulty/dual_variant_calc/call_volume_raw_vs_deduplicated
    """
    setup_call_volume_scene()
    data = validate_success(api.get_call_volume(ANALYST, params={**WINDOW, "view": "DEDUPLICATED"}))
    assert data["view"] == "DEDUPLICATED"
    # Distinct identified callers {A, B} = 2, plus one per anonymous session = 2.
    assert data["call_count"] == 4
    assert data["escalated_case_count"] == 1
    assert_escalation_rate(data["escalation_rate"], 0.25)  # 1/4


def test_analytics_do_not_aggregate_exclusion(api):
    """PRD §3.9: "Sessions whose caller has `do_not_aggregate` true are excluded
    from both views."
    PRD §3.4: "A revoked `DATA_SHARING` consent sets the caller's
    `do_not_aggregate` true, excluding them from analytics denominators."
    PRD §3.9: "The `escalation_rate` is 0 when `call_count` is 0, and otherwise the
    escalated count divided by the call count, rounded half-up to four decimal
    places; the same window and filters under the two views can therefore
    legitimately report different rates."

    Design: Corner/calculations/analytics_do_not_aggregate_exclusion
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    wrap_up_session(bundle, session["id"])
    consent = grant_consent(caller["id"], "DATA_SHARING")
    validate_success(api.revoke_consent(
        consent["id"], TEST_USERS["dpo_headers"]
    ))

    raw = validate_success(api.get_call_volume(ANALYST, params={**WINDOW, "view": "RAW"}))
    dedup = validate_success(api.get_call_volume(ANALYST, params={**WINDOW, "view": "DEDUPLICATED"}))
    assert raw["call_count"] == 0 and dedup["call_count"] == 0, (
        "the revoked DATA_SHARING consent excludes the caller's WRAPPED_UP session "
        "from both variants' denominators"
    )
    assert_escalation_rate(raw["escalation_rate"], 0)
    assert_escalation_rate(dedup["escalation_rate"], 0)


def test_analytics_zero_denominator(api):
    """PRD §3.9: "The `escalation_rate` is 0 when `call_count` is 0, and otherwise
    the escalated count divided by the call count, rounded half-up to four decimal
    places; the same window and filters under the two views can therefore
    legitimately report different rates. The response carries `call_count`,
    `escalated_case_count`, `escalation_rate`, and the echoed `view`."

    Design: Corner/calculations/analytics_zero_denominator
    """
    data = validate_success(api.get_call_volume(ANALYST, params={**WINDOW, "view": "RAW"}))
    assert data["call_count"] == 0
    assert data["escalated_case_count"] == 0
    assert_escalation_rate(data["escalation_rate"], 0)
    assert data["view"] == "RAW"


def test_analyst_cannot_read_cases(api):
    """PRD §3.9: "This read is available to `Analyst`, `HotlineSupervisor`, and
    `AgencyAdmin` — analysts see aggregates only and never caller-identified
    resources."
    PRD §2.1: "Each endpoint admits a defined set of roles (see §4); an
    authenticated party attempting an operation outside that set is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/analyst_cannot_read_cases
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)

    resp = api.get_case(case["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    data = validate_success(api.get_call_volume(ANALYST, params={**WINDOW, "view": "RAW"}))
    assert data["call_count"] == 1, (
        "the aggregate read remains available: one session reached ACTIVE"
    )
