"""Regulatory sweeps: penalty math, escalation cascade, freeze gate, deadlines."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_property, create_active_policy, create_approved_vendor, create_visitor,
    create_banner_config_payload, create_tag_rule_payload,
    create_tag_audit_scan_payload, run_scan_payload, observed_tracker,
    create_regulatory_sweep_payload, age_attestation_payload,
    create_consent_record_payload,
    make_auditor_headers, make_visitor_headers,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
VM = TEST_USERS["vendor_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]
ANY = TEST_USERS["any_headers"]
AUD1 = make_auditor_headers("aud-1")
AUD2 = make_auditor_headers("aud-2")


def _penalty_site(api):
    """Two CONFIRMED_VIOLATION MEDIUM findings created at the default clock."""
    prop = create_property(name="Penalty Site", sale_share_designation="SELLS_AND_SHARES")
    create_approved_vendor(
        prop["id"], legal_name="MismatchCo", declared_purposes=["ADVERTISING"],
        tracker_signatures=["bad-1.com", "bad-2.com"],
    )
    scan = get_success_data(
        api.create_tag_audit_scan(
            create_tag_audit_scan_payload(
                prop["id"], scheduled_start="2026-05-01T09:00:00Z", duration_minutes=30,
            ),
            AUD1,
        )
    )
    get_success_data(
        api.run_tag_audit_scan(
            scan["id"],
            run_scan_payload([
                observed_tracker("bad-1.com", "ANALYTICS"),
                observed_tracker("bad-2.com", "ANALYTICS"),
            ]),
            AUD1,
        )
    )
    findings, _m = validate_paginated(api.list_scan_findings(scan["id"], ANY))
    assert len(findings) == 2
    for f in findings:
        assert f["severity"] == "MEDIUM"
        validate_success(
            api.update_tracker_finding(f["id"], {"status": "CONFIRMED_VIOLATION"}, AUD2), 200
        )
    return prop


def test_sweep_penalty_round_per_finding_then_sum(api):
    """PRD section 3.8: "for each finding, the system takes the finding's age in
    whole days from its `created_at` to `escalated_at` (fractional days
    discarded), caps that age at thirty days, multiplies the severity base —
    250000 cents for `HIGH`, 77777 cents for `MEDIUM` — by one plus five
    hundredths per day of age (capped), rounds the resulting per-finding amount
    half-up to whole cents, and only then sums the rounded amounts into
    `penalty_exposure_cents`".

    Design: Difficulty/combinatorial_formula/sweep_penalty_round_per_finding_then_sum
    """
    prop = _penalty_site(api)
    # Findings created at 2026-05-01T00:00:00Z; escalate exactly 4 days later.
    get_success_data(api.set_clock({"to_iso8601": "2026-05-05T00:00:00Z"}, ADMIN))
    sweep = get_success_data(
        api.create_regulatory_sweep(
            create_regulatory_sweep_payload(
                prop["id"], regulator_ref="AG-2026-041", jurisdiction_code="US-CA",
                deadline_days=30,
            ),
            AUD1,
        )
    )
    escalated = validate_success(api.escalate_regulatory_sweep(sweep["id"], AUD1), 200)
    # Per finding: round_half_up(77777 * (1 + 0.05*4)) = round_half_up(93332.4) = 93332;
    # two findings summed -> 186664.
    assert escalated["penalty_exposure_cents"] == 186664
    assert escalated["status"] == "ESCALATED"


def test_sweep_penalty_is_not_sum_then_round(api):
    """PRD section 2.9: "each finding's amount is rounded half-up to whole cents
    **first**, and the rounded per-finding amounts are **then summed** into the
    sweep total. Summing raw amounts and rounding once at the end is a
    different, incorrect procedure and yields different totals."
    PRD section 3.8: "the property's `posture` flips to `FROZEN` (incrementing
    its `version`)".

    Design: Difficulty/combinatorial_formula/sweep_penalty_round_per_finding_then_sum
    """
    prop = _penalty_site(api)
    get_success_data(api.set_clock({"to_iso8601": "2026-05-05T00:00:00Z"}, ADMIN))
    sweep = get_success_data(
        api.create_regulatory_sweep(
            create_regulatory_sweep_payload(
                prop["id"], regulator_ref="AG-2026-042", jurisdiction_code="US-CA",
                deadline_days=30,
            ),
            AUD1,
        )
    )
    escalated = validate_success(api.escalate_regulatory_sweep(sweep["id"], AUD1), 200)
    assert escalated["penalty_exposure_cents"] == 186664
    assert escalated["penalty_exposure_cents"] != 186665, (
        "sum-then-round (round_half_up(186664.8)) is the wrong ordering"
    )
    prop_after = get_success_data(api.get_property(prop["id"], ANY))
    assert prop_after["posture"] == "FROZEN", "escalation cascade freezes the property"


def _cascade_site(api):
    prop = create_property(name="Cascade Site", sale_share_designation="SELLS_AND_SHARES")
    create_active_policy(
        prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_OUT_ALLOWED",
        min_consent_age=16, retention_days=30, gpc_honored=True,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    cfg = get_success_data(
        api.create_banner_config(
            create_banner_config_payload(
                prop["id"], jurisdiction_code="US-CA",
                categories_shown=["ADVERTISING", "SALE_SHARE"], config_label="v1",
            ),
            ADMIN,
        )
    )
    pv = get_success_data(api.get_property(prop["id"], ANY))["version"]
    cfg = get_success_data(
        api.publish_banner_config(cfg["id"], {"expected_property_version": pv}, ADMIN)
    )
    vend = create_approved_vendor(
        prop["id"], legal_name="TagCo", declared_purposes=["ADVERTISING"],
        tracker_signatures=["tag-1.com"],
    )
    rule = get_success_data(
        api.create_tag_rule(
            create_tag_rule_payload(vend["id"], cfg["id"], purpose_category="ADVERTISING"), VM
        )
    )
    sweep = get_success_data(
        api.create_regulatory_sweep(
            create_regulatory_sweep_payload(
                prop["id"], regulator_ref="FTC-9", jurisdiction_code="US-CA", deadline_days=30,
            ),
            AUD1,
        )
    )
    return prop, cfg, rule, sweep


def test_sweep_escalation_cascade_depth3(api):
    """PRD section 3.8: "the property's `posture` flips to `FROZEN` (incrementing
    its `version`); the freeze then pushes each `PUBLISHED` banner configuration
    of the property to `SUPPRESSED`; and each suppressed configuration in turn
    disables its `ENABLED` tag rules. Every link is caused by the previous one."

    Design: Difficulty/transitive_cascade/sweep_escalation_cascade_depth3
    """
    prop, cfg, rule, sweep = _cascade_site(api)
    escalated = validate_success(api.escalate_regulatory_sweep(sweep["id"], AUD1), 200)
    assert escalated["status"] == "ESCALATED"
    assert escalated["escalated_at"] == "2026-05-01T00:00:00.000Z", (
        "escalated_at is stamped with the current logical clock"
    )

    prop_after = get_success_data(api.get_property(prop["id"], ANY))
    assert prop_after["posture"] == "FROZEN", "link 1: posture flip"
    cfg_after = get_success_data(api.get_banner_config(cfg["id"], ANY))
    assert cfg_after["status"] == "SUPPRESSED", "link 2: caused by the posture flip"
    rule_after = get_success_data(api.get_tag_rule(rule["id"], ANY))
    assert rule_after["status"] == "DISABLED", "link 3: caused by the config suppression"


def test_sweep_escalation_freeze_gates_admin_mutations(api):
    """PRD section 2.6: "while `FROZEN`, policy activation/retirement/amendment,
    banner configuration creation, publication, and archival, vendor
    registration, approval, and suspension, tag rule creation and status
    changes, and consent grant or re-grant are all rejected with
    `ERR_PROPERTY_FROZEN` (409)."

    Design: Difficulty/transitive_cascade/sweep_escalation_cascade_depth3
    """
    prop, cfg, rule, sweep = _cascade_site(api)
    validate_success(api.escalate_regulatory_sweep(sweep["id"], AUD1), 200)

    res = api.create_banner_config(
        create_banner_config_payload(prop["id"], jurisdiction_code="US-CA",
                                     categories_shown=["ANALYTICS"], config_label="v2"),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_PROPERTY_FROZEN)
    res2 = api.update_tag_rule(rule["id"], {"status": "RETIRED"}, VM)
    validate_error(res2, ApiErrorId.ERR_PROPERTY_FROZEN)


def _frozen_child_site(api):
    prop = create_property(name="Frozen Site", sale_share_designation="SELLS_AND_SHARES")
    create_active_policy(
        prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_OUT_ALLOWED",
        min_consent_age=16, retention_days=30, gpc_honored=True,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    vis = create_visitor(prop["id"], external_ref="kid@x.com", jurisdiction_code="US-CA")
    get_success_data(
        api.attest_age(vis["id"], age_attestation_payload("2015-06-01T00:00:00Z"),
                       make_visitor_headers(vis["id"]))
    )
    sweep = get_success_data(
        api.create_regulatory_sweep(
            create_regulatory_sweep_payload(
                prop["id"], regulator_ref="AG-1", jurisdiction_code="US-CA", deadline_days=30,
            ),
            AUD1,
        )
    )
    validate_success(api.escalate_regulatory_sweep(sweep["id"], AUD1), 200)
    return prop, vis


def test_frozen_state_beats_child_safety_on_consent_grant(api):
    """PRD section 2.8: "Posture gate — the property must be `NORMAL` for
    frozen-gated operations (`ERR_PROPERTY_FROZEN`). This rung outranks every
    business rule below it: for example, a child visitor's grant attempt on a
    frozen property fails with `ERR_PROPERTY_FROZEN`, not
    `ERR_CHILD_CONSENT_FORBIDDEN`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_state_beats_child_safety_on_consent_grant
    """
    prop, vis = _frozen_child_site(api)
    res = api.create_consent_record(
        vis["id"], create_consent_record_payload("ADVERTISING"),
        make_visitor_headers(vis["id"]),
    )
    err = validate_error(res, ApiErrorId.ERR_PROPERTY_FROZEN)
    assert err["error_id"] != "ERR_CHILD_CONSENT_FORBIDDEN", (
        "the child-safety check would also fail, but the state gate wins"
    )
    assert res.status_code == 409, "state error (409), not the safety error's 403"


def test_frozen_property_rejects_grant_regardless_of_age(api):
    """PRD section 2.6: "while `FROZEN`, ... consent grant or re-grant are all
    rejected with `ERR_PROPERTY_FROZEN` (409)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_state_beats_child_safety_on_consent_grant
    """
    prop = create_property(name="Frozen Site", sale_share_designation="SELLS_AND_SHARES")
    create_active_policy(
        prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_OUT_ALLOWED",
        min_consent_age=16, retention_days=30, gpc_honored=True,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    vis = create_visitor(prop["id"], external_ref="adult@x.com", jurisdiction_code="US-CA")
    get_success_data(
        api.attest_age(vis["id"], age_attestation_payload("1990-01-01T00:00:00Z"),
                       make_visitor_headers(vis["id"]))
    )
    sweep = get_success_data(
        api.create_regulatory_sweep(
            create_regulatory_sweep_payload(
                prop["id"], regulator_ref="AG-2", jurisdiction_code="US-CA", deadline_days=30,
            ),
            AUD1,
        )
    )
    validate_success(api.escalate_regulatory_sweep(sweep["id"], AUD1), 200)
    res = api.create_consent_record(
        vis["id"], create_consent_record_payload("ANALYTICS"),
        make_visitor_headers(vis["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PROPERTY_FROZEN)


def test_sweep_respond_after_deadline_auto_escalates(api):
    """PRD section 3.8: "If the logical clock has passed `response_due_at` when
    a response is attempted, the sweep does not accept the response: it
    auto-transitions to `ESCALATED` and the respond call fails with
    `ERR_SWEEP_DEADLINE_PASSED`." Also: "the system stamps `response_due_at` as
    exactly that many days after creation."

    Design: Corner/state_machines/sweep_respond_after_deadline_auto_escalates
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    sweep = get_success_data(
        api.create_regulatory_sweep(
            create_regulatory_sweep_payload(
                prop["id"], regulator_ref="LATE-1", jurisdiction_code="US-CA", deadline_days=5,
            ),
            AUD1,
        )
    )
    assert sweep["response_due_at"] == "2026-05-06T00:00:00.000Z", (
        "created at the 2026-05-01 default clock plus 5 days"
    )
    get_success_data(api.set_clock({"to_iso8601": "2026-05-06T00:00:01Z"}, ADMIN))

    res = api.respond_regulatory_sweep(sweep["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_SWEEP_DEADLINE_PASSED)

    sweep_after = get_success_data(api.get_regulatory_sweep(sweep["id"], ANY))
    assert sweep_after["status"] == "ESCALATED", "deadline miss auto-escalated"
    prop_after = get_success_data(api.get_property(prop["id"], ANY))
    assert prop_after["posture"] == "FROZEN"


def test_sweep_close_from_open_rejected(api):
    """PRD section 3.8: "The sweep lifecycle runs `OPEN → EVIDENCE_COLLECTION →
    RESPONDED → CLOSED`, with escalation available from either `OPEN` or
    `EVIDENCE_COLLECTION`. ... Actions from any other status are rejected with
    `ERR_SWEEP_INVALID_STATE`."

    Design: Corner/state_machines/sweep_close_from_open_rejected
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    sweep = get_success_data(
        api.create_regulatory_sweep(
            create_regulatory_sweep_payload(
                prop["id"], regulator_ref="C-1", jurisdiction_code="US-CA", deadline_days=30,
            ),
            AUD1,
        )
    )
    res = api.close_regulatory_sweep(sweep["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_SWEEP_INVALID_STATE)


def test_auditor_cannot_respond_sweep(api):
    """PRD section 3.8: "responding — a `PrivacyAdmin` duty — moves it to
    `RESPONDED`". PRD section 2.1: "an attempt to perform an action outside the
    caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (403)."

    Design: Corner/rbac/auditor_cannot_respond_sweep
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    sweep = get_success_data(
        api.create_regulatory_sweep(
            create_regulatory_sweep_payload(
                prop["id"], regulator_ref="R-1", jurisdiction_code="US-CA", deadline_days=30,
            ),
            AUD1,
        )
    )
    res = api.respond_regulatory_sweep(sweep["id"], AUD1)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_sweep_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (..., `ERR_SWEEP_NOT_FOUND`)."

    Design: Corner/errors/sweep_get_not_found_returns_404
    """
    res = api.get_regulatory_sweep(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_SWEEP_NOT_FOUND)
