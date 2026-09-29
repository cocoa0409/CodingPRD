"""Cascades that must run every level, down to a grandparent's aggregates."""

from test_helpers import (
    TEST_USERS,
    assert_rights_dispute,
    assert_settlement_conservation,
    assert_subscriber_report,
    open_audit_finding,
    raise_rights_dispute,
    read_agreement,
    read_distributor,
    read_settlements,
    read_subscriber_report,
    resolve_audit_finding_payload,
    resolve_rights_dispute_payload,
    setup_issued_settlement,
    validate_success,
)


def _settled_scenario_with_streaming_dispute(api):
    ctx = setup_issued_settlement()
    ctx["dispute"] = raise_rights_dispute(
        ctx["agreement"]["id"], ctx["station"]["id"], "STREAMING"
    )
    return ctx


def test_excluded_rights_dispute_cascades_into_the_settlement_amounts(api):
    """Exclusion credits the settlement and re-splits it, leaving gross untouched.

    PRD §3.9: "For each rights dispute on this agreement in status
    `RESOLVED_EXCLUDED`, iterated in creation-timestamp ascending order, take
    `gross_fee_cents`, multiply by that dispute's rights credit in basis points - 800
    for `DIGITAL`, 500 for `OUT_OF_HOME`, 1,200 for `STREAMING` - divide by ten
    thousand, and round half up to whole cents."

    Design: Difficulty/transitive_cascade/rights_exclusion_cascades_four_levels_to_agreement_lifetime_ledger
    """
    ctx = _settled_scenario_with_streaming_dispute(api)

    response = api.resolve_rights_dispute(
        ctx["dispute"]["id"],
        resolve_rights_dispute_payload("EXCLUDED"),
        TEST_USERS["compliance_officer_headers"],
    )
    dispute = validate_success(response, 200)

    assert_rights_dispute(dispute)
    assert dispute["status"] == "RESOLVED_EXCLUDED"
    assert dispute["credit_bp_applied"] == 1200

    settlement = read_settlements(ctx["agreement"]["id"])[0]
    assert settlement["gross_fee_cents"] == 25000000
    assert settlement["rights_credit_cents"] == 3000000
    assert settlement["reverse_comp_cents"] == 12100000
    assert settlement["penetration_penalty_cents"] == 0
    assert settlement["net_retained_cents"] == 9900000
    assert_settlement_conservation(settlement)


def test_excluded_rights_dispute_rederives_the_agreement_lifetime_ledger(api):
    """The grant shrinks, the credit total rises, and the lifetime ledger follows.

    PRD §3.8: "At the fourth level, because those settlements changed, the parent
    agreement re-derives `lifetime_gross_fee_cents` and `lifetime_net_retained_cents`
    from the settlements now in status `ISSUED` or `TRUED_UP`."

    Design: Difficulty/transitive_cascade/rights_exclusion_cascades_four_levels_to_agreement_lifetime_ledger
    """
    ctx = _settled_scenario_with_streaming_dispute(api)
    assert ctx["agreement"]["granted_rights_scope"] == ["DIGITAL", "STREAMING"]
    version_before = read_agreement(ctx["agreement"]["id"])["version"]

    validate_success(
        api.resolve_rights_dispute(
            ctx["dispute"]["id"],
            resolve_rights_dispute_payload("EXCLUDED"),
            TEST_USERS["compliance_officer_headers"],
        ),
        200,
    )

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["granted_rights_scope"] == ["DIGITAL"]
    assert agreement["rights_credit_bp_total"] == 1200
    assert agreement["lifetime_gross_fee_cents"] == 25000000
    assert agreement["lifetime_net_retained_cents"] == 9900000
    assert agreement["version"] > version_before


def test_substantiated_finding_flags_the_settlement_without_repricing_it(api):
    """The audit cascade only sets the true-up flag; the money stays put.

    PRD §3.4: "The settlements themselves are not re-priced by this cascade; they are
    only flagged, and the actual re-pricing happens when a counsel trues them up as
    described in §3.9."

    Design: Difficulty/transitive_cascade/audit_substantiation_cascades_three_levels_to_true_up_flag
    """
    ctx = setup_issued_settlement()
    finding = open_audit_finding(
        ctx["report"]["id"], ctx["station"]["id"], adjustment_subscribers=6000
    )

    response = api.resolve_audit_finding(
        finding["id"],
        resolve_audit_finding_payload("SUBSTANTIATED"),
        TEST_USERS["compliance_officer_headers"],
    )
    resolved = validate_success(response, 200)
    assert resolved["status"] == "SUBSTANTIATED"

    settlement = read_settlements(ctx["agreement"]["id"])[0]
    assert settlement["true_up_required"] is True
    assert settlement["status"] == "ISSUED"
    assert settlement["basis_variant"] == "AS_REPORTED"
    assert settlement["billable_subscriber_basis_snapshot"] == 100000
    assert settlement["net_retained_cents"] == 11250000
    assert_settlement_conservation(settlement)


def test_substantiated_finding_raises_the_distributor_open_true_up_count(api):
    """The report is adjusted and the distributor's open-true-up counter follows.

    PRD §3.4: "At the third level, because `audit_adjustment_subscribers` is now
    non-zero, every fee settlement that drew its basis from this report and is still
    in status `ISSUED` has `true_up_required` set to true, and the distributor's
    `open_true_up_count` is recomputed."

    Design: Difficulty/transitive_cascade/audit_substantiation_cascades_three_levels_to_true_up_flag
    """
    ctx = setup_issued_settlement()
    assert read_distributor(ctx["distributor"]["id"])["open_true_up_count"] == 0
    finding = open_audit_finding(
        ctx["report"]["id"], ctx["station"]["id"], adjustment_subscribers=6000
    )

    validate_success(
        api.resolve_audit_finding(
            finding["id"],
            resolve_audit_finding_payload("SUBSTANTIATED"),
            TEST_USERS["compliance_officer_headers"],
        ),
        200,
    )

    report = read_subscriber_report(ctx["report"]["id"])
    assert_subscriber_report(report)
    assert report["status"] == "ADJUSTED"
    assert report["audit_adjustment_subscribers"] == 6000
    assert report["adjusted_subscriber_count"] == 106000
    assert report["billable_subscriber_basis"] == 106000
    assert report["as_reported_basis"] == 100000

    assert read_distributor(ctx["distributor"]["id"])["open_true_up_count"] == 1
