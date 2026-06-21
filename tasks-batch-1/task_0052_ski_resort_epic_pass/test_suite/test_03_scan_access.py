"""Scan-and-go lift access: the fixed-order scan decision pipeline, the
anti-passback half-open window boundary, IKON interchange branch ordering and
grants, resort-suspended dependency, blackout vs FULL_EPIC override, token
mismatch, not-active, and scan_count accounting.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
)

ADMIN = TEST_USERS["network_admin_headers"]
OPS = TEST_USERS["resort_ops_headers"]


def test_scan_decision_interchange_cap_denies_before_blackout(api):
    """PRD §3.3: "the number of distinct prior interchange scan-days this pass has
    already used at this resort must be strictly fewer than that agreement's
    `max_interchange_days`. If any of the three fails, the scan is denied with
    reason `NO_INTERCHANGE` and surfaced as `ERR_INTERCHANGE_DENIED`".
    PRD §3.3: "The count of distinct interchange days is the number of distinct
    `scan_date` values among the `GRANTED` scans already recorded for this pass at
    this resort, not counting the current scan."

    Design: Difficulty/combinatorial_formula/scan_decision_nonlinear_branch_ordering
    """
    fixtures.set_clock(api, "2026-02-01T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=5000, ikon_interchange_enabled=True,
        blackout_dates=[],
    )
    resort = fixtures.create_resort(api, name="Aspen IKON", home_network="IKON", gate_count=1)
    fixtures.create_interchange_agreement(api, resort["id"], max_interchange_days=1)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Holder D")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    first = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert first["result"] == "GRANTED", "first interchange scan uses the single allowed day"
    fixtures.set_clock(api, "2026-02-01T08:30:00Z")
    # PRD §3.3: the interchange rule is a denial-bearing rule that "both writes the
    # DENIED record and returns their corresponding error code" -> ERR_INTERCHANGE_DENIED.
    second = api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS)
    validate_error(second, ApiErrorId.ERR_INTERCHANGE_DENIED.value, 409)


def test_interchange_grant_when_agreement_active_and_days_available(api):
    """PRD §3.3: "the product's `ikon_interchange_enabled` must be true, an `ACTIVE`
    interchange agreement must exist for that resort, and the number of distinct
    prior interchange scan-days this pass has already used at this resort must be
    strictly fewer than that agreement's `max_interchange_days`... if all three
    hold the scan is granted."

    Design: Corner/endpoints/interchange_grant_when_agreement_active
    """
    fixtures.set_clock(api, "2026-03-08T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=5000, ikon_interchange_enabled=True,
        blackout_dates=[],
    )
    resort = fixtures.create_resort(api, name="Grant IKON", home_network="IKON")
    fixtures.create_interchange_agreement(api, resort["id"], max_interchange_days=2)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Grant Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    scan = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert scan["result"] == "GRANTED"


def test_anti_passback_halfopen_window_boundary(api):
    """PRD §3.3: "The cooldown is five minutes, evaluated in whole minutes as a
    half-open window — that is, a prior grant is blocking when the elapsed time
    from it to the current scan is zero or more minutes and strictly fewer than
    five minutes; a prior grant exactly five minutes earlier no longer blocks."

    Design: Difficulty/boundary_precision_check/anti_passback_halfopen_window_boundary
    """
    fixtures.set_clock(api, "2026-02-10T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=9000)
    resort = fixtures.create_resort(api, name="Whistler", home_network="EPIC", gate_count=2)
    issued = fixtures.issue_pass(api, product["id"], holder_name="APB Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    # X-1 baseline grant at 08:00
    s1 = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert s1["result"] == "GRANTED"
    # +4 min: inside the window -> denied. PRD §3.3: anti-passback is a
    # denial-bearing rule that returns its error code -> ERR_ANTI_PASSBACK.
    fixtures.set_clock(api, "2026-02-10T08:04:00Z")
    s2 = api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS)
    validate_error(s2, ApiErrorId.ERR_ANTI_PASSBACK.value, 409)
    # +5 min exactly: outside the half-open window -> GRANTED
    fixtures.set_clock(api, "2026-02-10T08:05:00Z")
    s3 = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert s3["result"] == "GRANTED", "a prior grant exactly five minutes earlier no longer blocks"


def test_anti_passback_clears_well_past_window(api):
    """PRD §3.3: "a prior grant is blocking when the elapsed time from it to the
    current scan is zero or more minutes and strictly fewer than five minutes; a
    prior grant exactly five minutes earlier no longer blocks."

    Design: Difficulty/boundary_precision_check/anti_passback_halfopen_window_boundary
    """
    fixtures.set_clock(api, "2026-02-11T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=9000)
    resort = fixtures.create_resort(api, name="Whistler2", home_network="EPIC", gate_count=2)
    issued = fixtures.issue_pass(api, product["id"], holder_name="APB Holder 2")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    s1 = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert s1["result"] == "GRANTED"
    # +6 minutes: comfortably outside the 5-minute half-open window -> GRANTED.
    fixtures.set_clock(api, "2026-02-11T08:06:00Z")
    s2 = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert s2["result"] == "GRANTED", "a prior grant six minutes earlier does not block"


def test_anti_passback_within_window_denied(api):
    """PRD §3.3: "if there exists a prior `GRANTED` scan for this same pass at this
    same resort whose `scan_at` falls within the cooldown ending strictly before
    the current `scan_at`, the scan is denied with reason `ANTI_PASSBACK`."

    Design: Difficulty/resource_temporal_overlap/anti_passback_buffer_window_overlap
    """
    fixtures.set_clock(api, "2026-03-01T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=9000)
    resort = fixtures.create_resort(api, name="Buffer Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Buffer Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    s1 = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert s1["result"] == "GRANTED"
    fixtures.set_clock(api, "2026-03-01T08:03:00Z")
    # PRD §3.3: anti-passback is a denial-bearing rule -> ERR_ANTI_PASSBACK.
    s2 = api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS)
    validate_error(s2, ApiErrorId.ERR_ANTI_PASSBACK.value, 409)


def test_anti_passback_is_scoped_per_resort(api):
    """PRD §3.3: "if there exists a prior `GRANTED` scan for this same pass at this
    same resort whose `scan_at` falls within the cooldown ending strictly before
    the current `scan_at`, the scan is denied with reason `ANTI_PASSBACK`."

    Design: Difficulty/resource_temporal_overlap/anti_passback_buffer_window_overlap
    """
    fixtures.set_clock(api, "2026-03-01T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=9000)
    resort_a = fixtures.create_resort(api, name="Buffer Mtn A", home_network="EPIC")
    resort_b = fixtures.create_resort(api, name="Buffer Mtn B", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Buffer Holder 2")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    s1 = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort_a["id"], token), OPS), 201
    )
    assert s1["result"] == "GRANTED"
    # Two minutes later at a DIFFERENT resort: the window is per pass+resort, so GRANTED.
    fixtures.set_clock(api, "2026-03-01T08:02:00Z")
    s2 = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort_b["id"], token), OPS), 201
    )
    assert s2["result"] == "GRANTED", \
        "anti-passback collides only on the SAME pass+resort; a different resort does not block"


def test_scan_decision_interchange_disabled_denies_no_interchange(api):
    """PRD §3.3: "when the scanning resort's `home_network` is `IKON`, the scan is
    treated as a cross-network interchange and three conditions must all hold — the
    product's `ikon_interchange_enabled` must be true... If any of the three fails,
    the scan is denied with reason `NO_INTERCHANGE` and surfaced as
    `ERR_INTERCHANGE_DENIED`".

    Design: Difficulty/combinatorial_formula/scan_decision_nonlinear_branch_ordering
    """
    fixtures.set_clock(api, "2026-02-02T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=5000, ikon_interchange_enabled=False,
        blackout_dates=[],
    )
    resort = fixtures.create_resort(api, name="Aspen IKON 2", home_network="IKON")
    fixtures.create_interchange_agreement(api, resort["id"], max_interchange_days=2)
    issued = fixtures.issue_pass(api, product["id"], holder_name="Holder E")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    # PRD §3.3: interchange is a denial-bearing rule that returns its error code
    # -> ERR_INTERCHANGE_DENIED.
    scan = api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS)
    validate_error(scan, ApiErrorId.ERR_INTERCHANGE_DENIED.value, 409)


def test_scan_denied_resort_suspended(api):
    """PRD §3.3: "the resort must be `OPEN`; if it is `SUSPENDED` the scan is denied
    with reason `RESORT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/scan_grant_requires_resort_open
    """
    fixtures.set_clock(api, "2026-01-25T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    resort = fixtures.create_resort(api, name="Suspended Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="ResortDep Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    validate_success(api.suspend_resort(resort["id"], ADMIN), 200)
    scan = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert scan["result"] == "DENIED"
    assert scan["denial_reason"] == "RESORT_SUSPENDED"


def test_scan_granted_when_resort_open(api):
    """PRD §3.3: "the resort must be `OPEN`; if it is `SUSPENDED` the scan is denied
    with reason `RESORT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/scan_grant_requires_resort_open
    """
    fixtures.set_clock(api, "2026-01-26T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    resort = fixtures.create_resort(api, name="Open Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="OpenResort Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    scan = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert scan["result"] == "GRANTED", \
        "the same token-valid ACTIVE pass scans GRANTED while the resort is OPEN"


def test_scan_token_mismatch_returns_error_and_records_denied(api):
    """PRD §3.3: "if the `presented_token` is not equal to the pass's
    `magnetic_token`, the scan is denied with reason `TOKEN_MISMATCH`. This is the
    highest-priority rule and is also surfaced to the caller as
    `ERR_TOKEN_MISMATCH`."

    Design: Corner/validations/scan_token_mismatch_returns_token_mismatch
    """
    fixtures.set_clock(api, "2026-03-02T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    resort = fixtures.create_resort(api, name="Tok Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Tok Holder")
    fixtures.activate_pass(api, issued["id"])
    resp = api.scan_pass(issued["id"], factories.scan_payload(resort["id"], "BOGUS"), OPS)
    validate_error(resp, ApiErrorId.ERR_TOKEN_MISMATCH.value, 409)


def test_scan_inactive_pass_denied_not_active(api):
    """PRD §3.3: "the pass must be `ACTIVE`; if it is in any other state the scan is
    denied with reason `NOT_ACTIVE`."

    Design: Corner/calculations/scan_inactive_pass_denied_not_active
    """
    fixtures.set_clock(api, "2026-02-27T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    resort = fixtures.create_resort(api, name="NotActive Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="NA Holder")
    token = issued["magnetic_token"]
    scan = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert scan["result"] == "DENIED"
    assert scan["denial_reason"] == "NOT_ACTIVE", \
        "scanning a token-valid but never-activated (ISSUED) pass is denied NOT_ACTIVE"


def test_full_epic_ignores_blackout_dates(api):
    """PRD §3.3: "`FULL_EPIC` products ignore blackout dates entirely and are always
    granted at this stage".

    Design: Corner/calculations/full_epic_ignores_blackout_dates
    """
    fixtures.set_clock(api, "2026-02-25T08:00:00Z")
    product = fixtures.create_product(
        api, tier="FULL_EPIC", price_cents=12000, blackout_dates=["2026-02-25"],
    )
    resort = fixtures.create_resort(api, name="Blackout Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="FE Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    scan = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert scan["result"] == "GRANTED", "FULL_EPIC scans GRANTED even on a listed blackout date"


def test_non_full_epic_blacked_out_on_listed_date(api):
    """PRD §3.3: "for any other tier, if the scan's `scan_date` is one of the
    product's `blackout_dates` the scan is denied with reason `BLACKOUT`."

    Design: Corner/calculations/non_full_epic_blacked_out_on_listed_date
    """
    fixtures.set_clock(api, "2026-02-26T08:00:00Z")
    product = fixtures.create_product(
        api, tier="LOCAL", price_cents=5000, blackout_dates=["2026-02-26"],
    )
    resort = fixtures.create_resort(api, name="Local Blackout", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Local Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    scan = validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    assert scan["result"] == "DENIED"
    assert scan["denial_reason"] == "BLACKOUT"


def test_scan_count_advances_only_on_granted(api):
    """PRD §3.3: "When a scan is granted, the pass is mutated: its `scan_count`
    increases by one... A denied scan still produces a persisted `LiftScan` row
    recording the denial, but it does not advance `scan_count` or the pass's
    `version`."

    Design: Corner/entities/scan_count_advances_only_on_granted
    """
    fixtures.set_clock(api, "2026-01-07T08:00:00Z")
    product = fixtures.create_product(api, tier="FULL_EPIC", price_cents=8000)
    resort = fixtures.create_resort(api, name="Count Mtn", home_network="EPIC")
    issued = fixtures.issue_pass(api, product["id"], holder_name="Count Holder")
    token = issued["magnetic_token"]
    fixtures.activate_pass(api, issued["id"])
    # Denied scan (token mismatch) — does not advance scan_count.
    api.scan_pass(issued["id"], factories.scan_payload(resort["id"], "WRONG_TOKEN"), OPS)
    after_denied = fixtures.get_pass(api, issued["id"])
    assert after_denied["scan_count"] == 0, "a denied scan does not advance scan_count"
    # Granted scan — advances to 1.
    validate_success(
        api.scan_pass(issued["id"], factories.scan_payload(resort["id"], token), OPS), 201
    )
    after_granted = fixtures.get_pass(api, issued["id"])
    assert after_granted["scan_count"] == 1, "a granted scan advances scan_count to 1"
