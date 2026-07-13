"""The abuse fork, the five-level suspension cascade, risk decay and reinstatement."""
from test_helpers import (
    ANALYST_1,
    ANALYST_2,
    SUPPORT,
    ApiErrorId,
    create_account,
    create_and_activate_subscription,
    create_dns_record,
    create_domain_payload,
    create_mailbox,
    create_plan,
    create_ssl_cert,
    decision_payload,
    file_report,
    get_account_state,
    get_add_on,
    get_domain,
    get_subscription,
    make_registrant_headers,
    reason_payload,
    register_and_activate_domain,
    report_under_review,
    run_sweep,
    set_clock,
    setup_account_with_active_domain,
    setup_auto_suspended_account,
    setup_hosting_stack,
    uphold_new_report,
    uphold_report,
    validate_error,
    validate_paginated,
    validate_success,
)


def _account_on_the_brink_of_auto_suspension():
    """Account with two domains, a subscription bound to NO domain, a mailbox and an SSL
    certificate on shop.net, a HIGH report on example.com already upheld (risk 30), and a
    CRITICAL report on shop.net sitting in UNDER_REVIEW.

    Returns (account, d1, d2, subscription, mailbox, ssl_cert, dns_record, pending_report).
    """
    account = create_account()
    d1 = register_and_activate_domain(account, "example", "com")
    d2 = register_and_activate_domain(account, "shop", "net")
    plan = create_plan()
    subscription = create_and_activate_subscription(account, plan)  # no primary domain
    mailbox = create_mailbox(account, subscription, d2, "sales", 2048)
    ssl_cert = create_ssl_cert(account, subscription, d2, term_days=90)
    dns_record = create_dns_record(d2, account, record_type="A", name="@",
                                   value="203.0.113.10")

    uphold_new_report(d1, severity="HIGH", category="SPAM")
    pending = report_under_review(d2, severity="CRITICAL", category="PHISHING")

    return account, d1, d2, subscription, mailbox, ssl_cert, dns_record, pending


# =========================================================================
# The five-level uphold cascade  (Difficulty/transitive_cascade)
# =========================================================================

def test_uphold_suspends_the_domain_and_carries_its_add_ons_and_dns_down_with_it(api):
    """PRD §3.9: "Level two: the reported domain transitions `ACTIVE → SUSPENDED` with
    `suspension_reason` set to `ABUSE`."
    PRD §3.9: "Level three, caused by that domain suspension: every `DnsRecord` of the domain
    has `serving_enabled` set to false; every `AddOn` of that domain whose `add_on_type` is
    `SSL_CERT` and whose `status` is `PENDING_VALIDATION` or `ACTIVE` transitions to
    `REVOKED` (a terminal state — the `validation_token` is retained for audit, but the
    certificate can never be revived); and every `AddOn` of that domain whose `add_on_type`
    is `EMAIL_MAILBOX` and whose `status` is `ACTIVE` transitions to `SUSPENDED`, keeping its
    storage reservation."

    Design: Difficulty/transitive_cascade/abuse_uphold_cascades_domain_addons_account_subscription
    """
    account, _d1, d2, _sub, mailbox, ssl_cert, dns_record, pending = (
        _account_on_the_brink_of_auto_suspension()
    )
    headers = make_registrant_headers(account["id"])

    upheld = uphold_report(pending["id"], decider="analyst-2", note="phishing confirmed")
    assert upheld["status"] == "UPHELD"
    assert upheld["decider_user_id"] == "analyst-2"

    suspended = get_domain(d2["id"], account)
    assert suspended["lifecycle_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "ABUSE"

    assert get_add_on(ssl_cert["id"], account)["status"] == "REVOKED"
    assert get_add_on(mailbox["id"], account)["status"] == "SUSPENDED"

    records, _meta = validate_paginated(api.list_dns_records(d2["id"], headers))
    assert records, "the zone must still hold its record"
    assert all(record["serving_enabled"] is False for record in records)
    assert dns_record["id"] in [record["id"] for record in records]


def test_uphold_recomputes_the_risk_score_which_auto_suspends_the_account_and_its_subscription(api):
    """PRD §3.9: "Level five, caused by the new score: if the recomputed `risk_score` is 70 or
    above, the account transitions `ACTIVE → SUSPENDED`, which in turn suspends every `ACTIVE`
    or `OVER_QUOTA` hosting subscription of that account and forces `auto_renew_enabled` to
    false on every domain it owns."
    PRD §3.5: "A *suspended* mailbox still holds its reservation; one that has become
    `EXPIRED`, `CANCELLED` or `REVOKED` does not."

    Design: Difficulty/transitive_cascade/abuse_uphold_cascades_domain_addons_account_subscription
    """
    account, _d1, _d2, subscription, _mailbox, _ssl, _dns, pending = (
        _account_on_the_brink_of_auto_suspension()
    )

    uphold_report(pending["id"], decider="analyst-2", note="phishing confirmed")

    state = get_account_state(account["id"])
    assert state["risk_score"] == 90, "HIGH 30 + CRITICAL 60, with no decay on day zero"
    assert state["status"] == "SUSPENDED"

    sub = get_subscription(subscription["id"], account)
    assert sub["status"] == "SUSPENDED"
    assert sub["storage_committed_mb"] == 2048, (
        "a SUSPENDED mailbox keeps its storage reservation"
    )


# =========================================================================
# The expiry-sweep cascade  (Difficulty/transitive_cascade)
# =========================================================================

def test_sweep_expiry_stops_the_zone_serving(api):
    """PRD §3.4: "If any one of those three conditions fails, the domain instead goes
    `ACTIVE → EXPIRED`, and that transition fires the outage cascade: every `DnsRecord` of the
    zone has `serving_enabled` set to false, every `HostingSubscription` whose
    `primary_domain_id` is this domain and whose `status` is `ACTIVE` or `OVER_QUOTA`
    transitions to `SUSPENDED`, and — as a consequence of those subscription suspensions —
    every `AddOn` of those subscriptions whose `status` is `ACTIVE` transitions to
    `SUSPENDED`."
    PRD §3.4: "The sweep reports what it did: `auto_renewed_count`, `expired_count`,
    `redemption_count`, `pending_delete_count`, `deleted_count` and `addon_expired_count`."

    Design: Difficulty/transitive_cascade/expiry_sweep_cascades_domain_subscription_addon
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    headers = make_registrant_headers(account["id"])
    record = create_dns_record(domain, account, record_type="A", name="@",
                               value="203.0.113.10")
    create_mailbox(account, subscription, domain, "info", 2048, term_days=730)

    set_clock("2027-05-02T00:00:00Z")
    report = run_sweep()

    assert report["expired_count"] == 1
    assert report["auto_renewed_count"] == 0

    expired = get_domain(domain["id"], account)
    assert expired["lifecycle_status"] == "EXPIRED", (
        "only one day into the 30-day grace, so not yet REDEMPTION"
    )

    records, _meta = validate_paginated(api.list_dns_records(domain["id"], headers))
    served = {rec["id"]: rec["serving_enabled"] for rec in records}
    assert served[record["id"]] is False


def test_sweep_expiry_suspends_the_primary_subscription_and_then_its_mailbox(api):
    """PRD §3.4: "If any one of those three conditions fails, the domain instead goes
    `ACTIVE → EXPIRED`, and that transition fires the outage cascade: every `DnsRecord` of the
    zone has `serving_enabled` set to false, every `HostingSubscription` whose
    `primary_domain_id` is this domain and whose `status` is `ACTIVE` or `OVER_QUOTA`
    transitions to `SUSPENDED`, and — as a consequence of those subscription suspensions —
    every `AddOn` of those subscriptions whose `status` is `ACTIVE` transitions to
    `SUSPENDED`."
    PRD §3.5: "A *suspended* mailbox still holds its reservation; one that has become
    `EXPIRED`, `CANCELLED` or `REVOKED` does not."

    Design: Difficulty/transitive_cascade/expiry_sweep_cascades_domain_subscription_addon
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    create_dns_record(domain, account, record_type="A", name="@", value="203.0.113.10")
    mailbox = create_mailbox(account, subscription, domain, "info", 2048, term_days=730)

    set_clock("2027-05-02T00:00:00Z")
    run_sweep()

    sub = get_subscription(subscription["id"], account)
    assert sub["status"] == "SUSPENDED"
    assert sub["storage_committed_mb"] == 2048

    assert get_add_on(mailbox["id"], account)["status"] == "SUSPENDED", (
        "the mailbox ends_at is 2028-04-30, so it is suspended by the cascade, not expired"
    )


# =========================================================================
# The risk-score threshold  (Difficulty/boundary_precision_check)
# =========================================================================

def _three_reported_domains():
    """Account with example.com, shop.net and blog.xyz; the two HIGH reports on the first
    two domains are already upheld (risk 60), the LOW report on blog.xyz is UNDER_REVIEW."""
    account = create_account()
    d1 = register_and_activate_domain(account, "example", "com")
    d2 = register_and_activate_domain(account, "shop", "net")
    d3 = register_and_activate_domain(account, "blog", "xyz")

    uphold_new_report(d1, severity="HIGH", category="SPAM")
    uphold_new_report(d2, severity="HIGH", category="SPAM")
    pending = report_under_review(d3, severity="LOW", category="COPYRIGHT")
    return account, d3, pending


def test_two_upheld_high_reports_leave_the_account_below_the_threshold(api):
    """PRD §3.9: "The auto-suspension threshold is 70, reached at 70 and not merely above it:
    two upheld `HIGH` reports decided today total 60 and leave the account alone, while a
    `CRITICAL` plus a `LOW` decided today total 70 and suspend it."
    PRD §3.9: "Each upheld report contributes its severity weight — 10 for `LOW`, 30 for
    `HIGH`, 60 for `CRITICAL` — halved once for every completed 90-day half-life that has
    elapsed since its `decided_at`."

    Design: Difficulty/boundary_precision_check/risk_score_at_exactly_70_auto_suspends_the_account
    """
    account, _d3, _pending = _three_reported_domains()

    state = get_account_state(account["id"], SUPPORT)
    assert state["risk_score"] == 60, "30 + 30, no decay on day zero"
    assert state["status"] == "ACTIVE", "60 is below the threshold of 70"


def test_a_third_upheld_low_report_lands_on_exactly_seventy_and_suspends_the_account(api):
    """PRD §3.1: "When the abuse cascade of §3.9 pushes an account's `risk_score` to 70 or
    above — at or above the threshold, not strictly above it — the account transitions
    `ACTIVE → SUSPENDED`."
    PRD §3.9: "The auto-suspension threshold is 70, reached at 70 and not merely above it:
    two upheld `HIGH` reports decided today total 60 and leave the account alone, while a
    `CRITICAL` plus a `LOW` decided today total 70 and suspend it."

    Design: Difficulty/boundary_precision_check/risk_score_at_exactly_70_auto_suspends_the_account
    """
    account, d3, pending = _three_reported_domains()

    uphold_report(pending["id"], decider="analyst-2")

    state = get_account_state(account["id"], SUPPORT)
    assert state["risk_score"] == 70, "30 + 30 + 10"
    assert state["status"] == "SUSPENDED", (
        "landing exactly on 70 suspends: the rule is >= 70, not > 70"
    )
    assert get_domain(d3["id"], account)["lifecycle_status"] == "SUSPENDED"


# =========================================================================
# Corner instances
# =========================================================================

def test_upholding_a_report_that_was_never_reviewed_is_rejected(api):
    """PRD §3.9: "A review attempted on a report that is not `OPEN`, or a decision attempted
    on a report that is not `UNDER_REVIEW`, is refused with `ERR_ABUSE_REPORT_INVALID_STATE`."

    Design: Corner/state_machines/uphold_an_open_report_without_review_rejected
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    report = file_report(domain, severity="CRITICAL", category="MALWARE")

    resp = api.uphold_abuse_report(
        report["id"], decision_payload("skip the review"), ANALYST_2
    )
    validate_error(resp, ApiErrorId.ERR_ABUSE_REPORT_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_abuse_report(report["id"], ANALYST_1))
    assert unchanged["status"] == "OPEN"
    assert unchanged["decider_user_id"] is None

    assert get_domain(domain["id"], account)["lifecycle_status"] == "ACTIVE"
    assert get_account_state(account["id"], SUPPORT)["risk_score"] == 0


def test_the_reviewing_analyst_may_not_decide_the_report_they_reviewed(api):
    """PRD §3.9: "If the deciding analyst's `X-User-ID` equals the report's
    `reviewer_user_id`, the decision is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "**Dismissal** — `UNDER_REVIEW → DISMISSED`, terminal — records
    `decider_user_id`, `decided_at` and the `decision_note`, and does nothing else at all: no
    domain changes, no account changes, no risk-score change."

    Design: Corner/validations/reviewer_cannot_uphold_the_report_they_reviewed
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    report = report_under_review(domain, severity="LOW", category="SPAM",
                                 reviewer="analyst-1")

    self_decide = api.uphold_abuse_report(
        report["id"], decision_payload("self decide"), ANALYST_1
    )
    validate_error(self_decide, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    held = validate_success(api.get_abuse_report(report["id"], ANALYST_1))
    assert held["status"] == "UNDER_REVIEW"
    assert get_domain(domain["id"], account)["lifecycle_status"] == "ACTIVE"

    dismissed = validate_success(
        api.dismiss_abuse_report(
            report["id"], decision_payload("not abusive"), ANALYST_2
        )
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["decider_user_id"] == "analyst-2"

    assert get_account_state(account["id"], SUPPORT)["risk_score"] == 0
    assert get_domain(domain["id"], account)["lifecycle_status"] == "ACTIVE", (
        "the DISMISSED branch has an empty side-effect set"
    )


def test_the_sweep_refreshes_risk_decay_by_one_half_per_completed_ninety_days(api):
    """PRD §3.9: "Concretely: the report's age in days is the elapsed time from `decided_at`
    to the logical clock now, taken in whole days (any partial day is discarded); that age is
    divided by 90 and the quotient rounded *down* to a whole number of half-lives; and the
    severity weight is multiplied by one half raised to that power."
    PRD §3.9: "The score is recomputed at exactly two moments: whenever an uphold suspends one
    of the account's domains, and on every expiry sweep, where the decay is refreshed so that
    an account's risk falls as its history ages."

    Design: Corner/calculations/risk_score_decays_by_half_every_ninety_days
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    uphold_new_report(domain, severity="HIGH", category="SPAM")

    before = get_account_state(account["id"], SUPPORT)
    assert before["risk_score"] == 30
    assert before["status"] == "ACTIVE"

    set_clock("2026-11-01T00:00:00Z")  # 184 days after decided_at
    run_sweep()

    after = get_account_state(account["id"], SUPPORT)
    assert after["risk_score"] == 8, (
        "30 * 0.5 ** floor(184 / 90) == 7.5, rounded half up to 8"
    )
    assert after["status"] == "ACTIVE"
    assert get_domain(domain["id"], account)["lifecycle_status"] == "SUSPENDED", (
        "decay never un-suspends anything"
    )


def test_account_reinstatement_revives_subscriptions_but_not_domains_or_certificates(api):
    """PRD §3.1: "A reinstatement moves the account `SUSPENDED → ACTIVE`, brings every
    `SUSPENDED` subscription of the account back to `ACTIVE`, and brings every `SUSPENDED`
    add-on of those subscriptions back to `ACTIVE` as well."
    PRD §3.1: "What it does *not* do is lift domain suspensions: a domain suspended for abuse
    stays `SUSPENDED` and must be reinstated individually, one name at a time, which is
    exactly the deliberate friction trust-and-safety asked for."
    PRD §3.9: "Revoked certificates are *not* revived. The compensation is asymmetric by
    design: a suspended mailbox can be turned back on, but a revoked certificate is gone for
    good."

    Design: Corner/state_machines/account_reinstate_revives_subscriptions_but_not_domains
    """
    account = create_account()
    d1 = register_and_activate_domain(account, "example", "com")
    d2 = register_and_activate_domain(account, "shop", "net")
    plan = create_plan()
    subscription = create_and_activate_subscription(account, plan)
    mailbox = create_mailbox(account, subscription, d1, "info", 2048)
    ssl_cert = create_ssl_cert(account, subscription, d1, term_days=90)

    uphold_new_report(d1, severity="CRITICAL", category="PHISHING")
    uphold_new_report(d2, severity="HIGH", category="MALWARE")

    before = get_account_state(account["id"], SUPPORT)
    assert before["risk_score"] == 90
    assert before["status"] == "SUSPENDED"

    reinstated = validate_success(
        api.reinstate_account(
            account["id"], reason_payload("customer remediated"), SUPPORT
        )
    )
    assert reinstated["status"] == "ACTIVE"

    assert get_subscription(subscription["id"], account)["status"] == "ACTIVE"
    assert get_add_on(mailbox["id"], account)["status"] == "ACTIVE"
    assert get_add_on(ssl_cert["id"], account)["status"] == "REVOKED"
    assert get_domain(d1["id"], account)["lifecycle_status"] == "SUSPENDED"
    assert get_domain(d2["id"], account)["lifecycle_status"] == "SUSPENDED"


def test_reinstating_an_active_domain_is_rejected(api):
    """PRD §3.9: "The domain must be `SUSPENDED` (anything else is `ERR_INVALID_DOMAIN_STATE`)
    and its account must already be back to `ACTIVE` — a domain belonging to a suspended
    account cannot be reinstated first."

    Design: Corner/state_machines/reinstate_an_active_domain_returns_invalid_domain_state
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)

    resp = api.reinstate_domain(domain["id"], reason_payload("customer asked"), SUPPORT)
    validate_error(resp, ApiErrorId.ERR_INVALID_DOMAIN_STATE.value, 409)

    unchanged = get_domain(domain["id"], account)
    assert unchanged["lifecycle_status"] == "ACTIVE"
    assert unchanged["suspension_reason"] is None


def test_a_suspended_account_may_not_register_a_new_domain(api):
    """PRD §2.8: "Next comes the `Registrant` ownership check (`ERR_NOT_RESOURCE_OWNER`), then
    the abuse-analyst segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`), then the two
    optimistic-concurrency checks of §2.6, then the account-suspension gate: a `Registrant`
    whose `Account.status` is `SUSPENDED` may not make any mutating request, and is refused
    with `ERR_ACCOUNT_SUSPENDED` (403)."

    Design: Corner/validations/suspended_account_cannot_register_a_new_domain
    """
    account, _d1, _d2 = setup_auto_suspended_account()
    headers = make_registrant_headers(account["id"])

    state = get_account_state(account["id"], SUPPORT)
    assert state["status"] == "SUSPENDED"
    assert state["risk_score"] == 90

    resp = api.create_domain(
        create_domain_payload(account["id"], domain_name="another", tld="io"), headers
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value, 403)

    _, meta = validate_paginated(
        api.list_domains(headers, {"account_id": account["id"]})
    )
    assert meta["total_count"] == 2, "no third domain was created"
