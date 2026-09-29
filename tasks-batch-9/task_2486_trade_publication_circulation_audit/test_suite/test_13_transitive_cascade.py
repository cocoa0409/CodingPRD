"""Multi-hop cascades: a condemning report down to the credit pool, and a sweep up to staleness."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_BREAKDOWN_STALE
from test_helpers.assertions import assert_credit_buckets, assert_ledger_buckets, assert_pct
from test_helpers.factories import certify_payload, undeliverable_event_payload
from test_helpers.fixtures import (
    add_complete_rule_set,
    certify_statement,
    issue_report,
    move_clock,
    offer_make_good,
    open_engagement,
    open_statement,
    qualify_subscriber,
    read_contract,
    read_publication,
    read_statement,
    read_subscriber,
    record_sample,
    register_contract,
    register_publication,
    run_hygiene_sweep,
    settle_guarantees,
)
from test_helpers.test_users import EXECUTIVE_HEADERS, MANAGER_HEADERS

PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
AUDIT_CLOCK = "2026-10-01T00:00:00Z"


def enrol(publication_id, company_name, subscription_class, copies, **extra):
    return qualify_subscriber(
        publication_id,
        signed_at="2026-07-01T00:00:00Z",
        captured_at="2026-07-15T00:00:00Z",
        company_name=company_name,
        subscription_class=subscription_class,
        copies=copies,
        **extra,
    )


def draft_for_the_quarter(publication_id, expected_total):
    """Open the DRAFT statement over the closed quarter and check its total."""
    statement = open_statement(
        publication_id,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AS_OF_PERIOD_END",
    )
    assert statement["total_qualified_copies"] == expected_total
    return statement


def reconcile(statement_id, subscriber_id, verified_copies):
    engagement = open_engagement(
        statement_id,
        auditor_org="Verified Audit Bureau",
        fieldwork_start="2026-10-05T00:00:00Z",
        fieldwork_end="2026-10-09T00:00:00Z",
        sample_size=1,
    )
    reconciling = record_sample(
        engagement["id"], subscriber_id, evidence_ok=True, verified_copies=verified_copies
    )
    assert reconciling["status"] == "RECONCILIATION"
    assert reconciling["verified_qualified_copies"] == verified_copies
    return engagement


def test_condemning_report_cascades_five_hops_into_the_credit_pool():
    """One report walks statement, publication, contract and obligation in a single request.

    "**Hop 5** — because those contracts left `ACTIVE` — moves each of their
    make-good obligations standing in `PENDING` or `OFFERED` to `VOID`, recording
    `closed_reason` as the literal string `RESTATEMENT_REQUIRED_CASCADE` rather than
    any operator text."

    Design: Difficulty/transitive_cascade/issue_report_five_hop_restatement_cascade
    """
    publication = register_publication(
        name="Cascade Depth Monthly",
        industry_code="MANUFACTURING",
        materiality_pct=2.00,
    )
    add_complete_rule_set(publication["id"])
    recipient = enrol(
        publication["id"], "Victor Paid Works", "PAID", 1200, paid_amount_cents=96000
    )
    contract = register_contract(
        publication["id"],
        advertiser_name="Cascade Media Buying",
        insertion_count=12,
        gross_rate_cents_per_insertion=850000,
        guaranteed_rate_base=1750,
        shortfall_tolerance_pct=2.00,
    )

    move_clock(AUDIT_CLOCK)
    statement = draft_for_the_quarter(publication["id"], 1200)
    filed = certify_statement(statement["id"])
    assert filed["declared_total_copies"] == 1200

    obligation = settle_guarantees(filed["id"])[0]
    assert obligation["credit_cents"] == 4808796
    offered = offer_make_good(obligation["id"])
    assert offered["status"] == "OFFERED"
    committed = read_contract(contract["id"])
    assert_credit_buckets(committed, committed=4808796, available=5391204)

    engagement = reconcile(filed["id"], recipient["subscriber"]["id"], 900)

    reported = issue_report(engagement["id"], report_note="300 copies unsupported")
    # Hop 1: the arithmetic lands on the statement and closes the engagement.
    assert reported["status"] == "REPORT_ISSUED"
    condemned = read_statement(filed["id"])
    assert condemned["discrepancy_copies"] == 300
    assert_pct(condemned["discrepancy_pct"], 25.00)
    # Hop 2: crossing materiality condemns the statement.
    assert condemned["status"] == "RESTATEMENT_REQUIRED"

    # Hop 3: the condemned statement freezes its publication.
    frozen = read_publication(publication["id"])
    assert frozen["audit_posture"] == "FROZEN"

    # Hop 4: the freeze suspends every active guarantee.
    suspended = read_contract(contract["id"])
    assert suspended["guarantee_status"] == "SUSPENDED_PENDING_RESTATEMENT"

    # Hop 5: the suspension voids the live obligation and returns its cents.
    voided = validate_success(
        api_client.get_make_good(obligation["id"], MANAGER_HEADERS), 200
    )
    assert voided["status"] == "VOID"
    assert voided["closed_reason"] == "RESTATEMENT_REQUIRED_CASCADE"
    assert_credit_buckets(
        suspended,
        pool=10200000,
        committed=0,
        waived=0,
        available=10200000,
    )


def test_immaterial_report_fires_no_hop_of_the_cascade():
    """Below materiality the report clears the statement and touches nothing downstream.

    "When `discrepancy_pct` is strictly below `materiality_pct` **and** the statement
    is in `UNDER_AUDIT`, the statement moves `UNDER_AUDIT → AUDIT_CLEARED` and
    **nothing downstream happens at all**: advertiser contracts keep their
    `guarantee_status`, no obligation changes status, and the publication's posture
    is unaffected by the report itself."

    Design: Difficulty/transitive_cascade/issue_report_five_hop_restatement_cascade
    """
    publication = register_publication(
        name="Immaterial Variance Monthly",
        industry_code="MANUFACTURING",
        materiality_pct=2.00,
    )
    add_complete_rule_set(publication["id"])
    recipient = enrol(
        publication["id"], "Whiskey Paid Works", "PAID", 1200, paid_amount_cents=96000
    )
    contract = register_contract(
        publication["id"],
        advertiser_name="Steady Media Buying",
        insertion_count=12,
        gross_rate_cents_per_insertion=850000,
        guaranteed_rate_base=1750,
        shortfall_tolerance_pct=2.00,
    )

    move_clock(AUDIT_CLOCK)
    statement = draft_for_the_quarter(publication["id"], 1200)
    filed = certify_statement(statement["id"])

    obligation = settle_guarantees(filed["id"])[0]
    offered = offer_make_good(obligation["id"])
    assert offered["status"] == "OFFERED"

    engagement = reconcile(filed["id"], recipient["subscriber"]["id"], 1188)
    assert read_statement(filed["id"])["status"] == "UNDER_AUDIT"

    reported = issue_report(engagement["id"], report_note="variance within tolerance")
    assert reported["status"] == "REPORT_ISSUED"

    cleared = read_statement(filed["id"])
    assert cleared["discrepancy_copies"] == 12
    # 12 of 1,200 is 1.00 percent, strictly below the 2.00 threshold.
    assert_pct(cleared["discrepancy_pct"], 1.00)
    assert cleared["status"] == "AUDIT_CLEARED"

    assert read_publication(publication["id"])["audit_posture"] == "OPEN"
    untouched = read_contract(contract["id"])
    assert untouched["guarantee_status"] == "ACTIVE"
    assert_credit_buckets(untouched, committed=4808796, waived=0, available=5391204)

    still_offered = validate_success(
        api_client.get_make_good(obligation["id"], MANAGER_HEADERS), 200
    )
    assert still_offered["status"] == "OFFERED"
    assert still_offered["closed_reason"] is None


def bounce(subscriber_id, reason_code="RETURNED_NO_FORWARDING"):
    response = api_client.record_undeliverable_event(
        subscriber_id, undeliverable_event_payload(reason_code=reason_code), MANAGER_HEADERS
    )
    return validate_success(response, 200)


def test_hygiene_sweep_cascades_from_a_drop_through_posture_into_staleness():
    """One sweep moves the delivery bucket, flips the posture and blocks certification.

    "But *any* change of posture, in either direction and between any two values,
    marks every `DRAFT` statement of the publication as having a stale breakdown,
    which does block certification until the breakdown is recomputed."

    Design: Difficulty/transitive_cascade/hygiene_sweep_three_hop_posture_staleness_cascade
    """
    publication = register_publication(
        name="Sweep Cascade Monthly",
        industry_code="MANUFACTURING",
        undeliverable_restrict_pct=5.00,
    )
    add_complete_rule_set(publication["id"])
    bulk = enrol(
        publication["id"], "X-ray Paid Works", "PAID", 950, paid_amount_cents=76000
    )
    wanderer = enrol(publication["id"], "Yankee Directed Works", "CONTROLLED", 50)

    move_clock(AUDIT_CLOCK)
    statement = draft_for_the_quarter(publication["id"], 1000)
    assert statement["status"] == "DRAFT"
    assert statement["breakdown_stale"] is False
    assert read_publication(publication["id"])["audit_posture"] == "OPEN"

    bounce(wanderer["subscriber"]["id"])
    twice = bounce(wanderer["subscriber"]["id"])
    assert twice["undeliverable_count"] == 2
    # Counters alone change nothing: the posture and the draft are still clean.
    assert read_publication(publication["id"])["audit_posture"] == "OPEN"
    assert read_statement(statement["id"])["breakdown_stale"] is False

    sweep = run_hygiene_sweep(publication["id"], run_type="UNDELIVERABLE_SWEEP")
    # Hop 1: the drop moves 50 copies out of the clean bucket.
    assert sweep["removed_count"] == 1
    assert sweep["requalification_required_count"] == 1
    assert sweep["undeliverable_flagged_count"] == 0

    dropped = read_subscriber(wanderer["subscriber"]["id"])
    assert dropped["delivery_status"] == "REMOVED"
    assert dropped["qualification_status"] == "REQUALIFICATION_REQUIRED"

    ledger = read_publication(publication["id"])
    assert_ledger_buckets(
        ledger, total=1000, deliverable=950, undeliverable=0, removed=50
    )
    # Hop 2: 50 of 1,000 is exactly 5.00 percent, which meets the restrict threshold.
    assert_pct(ledger["undeliverable_pct"], 5.00)
    assert sweep["posture_before"] == "OPEN"
    assert sweep["posture_after"] == "RESTRICTED"
    assert ledger["audit_posture"] == "RESTRICTED"

    # Hop 3: the posture moved, so the one open draft was marked.
    assert sweep["statements_invalidated_count"] == 1
    stale = read_statement(statement["id"])
    assert stale["breakdown_stale"] is True
    # The frozen figures themselves were not rewritten by the sweep.
    assert stale["total_qualified_copies"] == 1000

    validate_error(
        api_client.certify_statement(
            statement["id"], certify_payload(), EXECUTIVE_HEADERS
        ),
        ERR_BREAKDOWN_STALE,
        409,
    )
    blocked = read_statement(statement["id"])
    assert blocked["status"] == "DRAFT"
    assert blocked["filed_at"] is None
    # RESTRICTED never blocks certification by itself; only the staleness does.
    assert read_subscriber(bulk["subscriber"]["id"])["delivery_status"] == "DELIVERABLE"


def test_hygiene_sweep_that_leaves_the_posture_alone_stops_after_one_hop():
    """A flag below the threshold ratio moves copies but never reaches the drafts.

    "When the posture did not move, no draft is marked by the sweep and
    `statements_invalidated_count` is 0."

    Design: Difficulty/transitive_cascade/hygiene_sweep_three_hop_posture_staleness_cascade
    """
    publication = register_publication(
        name="Shallow Sweep Monthly",
        industry_code="MANUFACTURING",
        undeliverable_restrict_pct=5.00,
    )
    add_complete_rule_set(publication["id"])
    enrol(publication["id"], "Zulu Paid Works", "PAID", 990, paid_amount_cents=79200)
    wanderer = enrol(publication["id"], "Alfa Directed Works", "CONTROLLED", 10)

    move_clock(AUDIT_CLOCK)
    statement = draft_for_the_quarter(publication["id"], 1000)
    assert statement["breakdown_stale"] is False

    once = bounce(wanderer["subscriber"]["id"])
    assert once["undeliverable_count"] == 1

    sweep = run_hygiene_sweep(publication["id"], run_type="UNDELIVERABLE_SWEEP")
    # One bounce is at least one but strictly fewer than the default threshold of 2.
    assert sweep["undeliverable_flagged_count"] == 1
    assert sweep["removed_count"] == 0
    assert sweep["requalification_required_count"] == 0

    flagged = read_subscriber(wanderer["subscriber"]["id"])
    assert flagged["delivery_status"] == "UNDELIVERABLE"
    assert flagged["qualification_status"] == "QUALIFIED"

    ledger = read_publication(publication["id"])
    assert_ledger_buckets(
        ledger, total=1000, deliverable=990, undeliverable=10, removed=0
    )
    # 10 of 1,000 is 1.00 percent, strictly below the 5.00 threshold.
    assert_pct(ledger["undeliverable_pct"], 1.00)
    assert sweep["posture_before"] == "OPEN"
    assert sweep["posture_after"] == "OPEN"
    assert ledger["audit_posture"] == "OPEN"

    # The cascade stops here: the draft is untouched and still certifiable.
    assert sweep["statements_invalidated_count"] == 0
    assert read_statement(statement["id"])["breakdown_stale"] is False

    filed = certify_statement(statement["id"])
    assert filed["status"] == "FILED"
    assert filed["declared_total_copies"] == 1000
