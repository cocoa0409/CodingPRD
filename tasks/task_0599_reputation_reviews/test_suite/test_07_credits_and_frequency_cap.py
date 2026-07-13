"""Enqueue gates: consent, the per-contact cooldown, credit availability and release."""

from test_helpers import (
    ApiErrorId,
    assert_credit_ledger,
    assert_instant_equals,
    assert_review_request,
    assert_spendable_credits,
    enqueue_request,
    read_campaign,
    read_review_request,
    set_clock,
    setup_running_email_campaign,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Consent beats the cooldown
# ---------------------------------------------------------------------------
def _setup_opted_out_contact_inside_its_cooldown(api, admin_headers):
    env = setup_running_email_campaign(
        num_contacts=1, business_overrides={"default_frequency_cap_days": 30}
    )
    contact = env["contacts"][0]
    enqueue_request(env["campaign"]["id"], contact["id"])

    set_clock("2026-05-10T00:00:00Z")
    validate_success(api.opt_out_contact(contact["id"], admin_headers))

    env["contact"] = contact
    return env


def test_an_opted_out_contact_inside_its_cooldown_reports_the_consent_failure(api, admin_headers):
    """PRD §3.6: "First, **consent**, which beats every commercial rule beneath it. The
    contact must not have `opted_out` set."
    PRD §3.6: "Any failure is `ERR_CONTACT_OPTED_OUT` (403)."
    PRD §2.9: "Note in particular that compliance beats commerce: a frozen location, an
    opted-out contact and a segregation-of-duties breach all surface *before* the fiscal
    checks, so an operator can never mask a compliance failure behind a credit failure."

    Design: Difficulty/priority_pair_validation_conflict/contact_opt_out_beats_frequency_cap_on_enqueue
    """
    env = _setup_opted_out_contact_inside_its_cooldown(api, admin_headers)

    resp = api.create_review_request(
        env["campaign"]["id"], {"contact_id": env["contact"]["id"]}, admin_headers
    )
    # The contact is simultaneously opted out (order 12) and inside its 30-day cooldown
    # (order 21); the consent check is the earlier one and must be the reported failure.
    validate_error(resp, ApiErrorId.ERR_CONTACT_OPTED_OUT.value)


def test_the_consent_rejection_reserves_no_extra_credit(api, admin_headers):
    """PRD §3.6: "On success, one credit is reserved (`credits_reserved` rises by one), the
    contact's `last_requested_at` is stamped with the current logical instant and its
    `request_count` rises by one."
    PRD §2.9: "12. Contact consent (`ERR_CONTACT_OPTED_OUT`)."

    Design: Difficulty/priority_pair_validation_conflict/contact_opt_out_beats_frequency_cap_on_enqueue
    """
    env = _setup_opted_out_contact_inside_its_cooldown(api, admin_headers)

    resp = api.create_review_request(
        env["campaign"]["id"], {"contact_id": env["contact"]["id"]}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_CONTACT_OPTED_OUT.value)

    campaign = read_campaign(env["campaign"]["id"])
    assert campaign["credits_reserved"] == 1, "only the original request still holds a credit"

    contacts = validate_success(
        api.list_contacts(env["business"]["id"], admin_headers)
    )
    contact = [row for row in contacts if row["id"] == env["contact"]["id"]][0]
    assert contact["request_count"] == 1, "the refused enqueue must not raise request_count"
    assert contact["opted_out"] is True


# ---------------------------------------------------------------------------
# The half-open per-contact cooldown
# ---------------------------------------------------------------------------
def _setup_contact_with_one_request_at_the_clock_start():
    env = setup_running_email_campaign(
        num_contacts=1, business_overrides={"default_frequency_cap_days": 30}
    )
    env["contact"] = env["contacts"][0]
    env["first_request"] = enqueue_request(env["campaign"]["id"], env["contact"]["id"])
    return env


def test_enqueue_one_second_before_the_cooldown_ends_is_rejected(api, admin_headers):
    """PRD §3.6: "Otherwise the cooldown occupies the half-open interval that begins at the
    anchor and runs for the tenant's `default_frequency_cap_days`. An enqueue is rejected
    with `ERR_FREQUENCY_CAP_ACTIVE` (409) whenever the current logical instant is at or
    after the anchor and strictly before the anchor plus the cap; an enqueue at *exactly*
    the anchor plus the cap is allowed, because the interval's end is exclusive."

    Design: Difficulty/resource_temporal_overlap/contact_frequency_cap_half_open_window_rejects_then_allows_at_exact_end
    """
    env = _setup_contact_with_one_request_at_the_clock_start()

    set_clock("2026-05-30T23:59:59Z")
    resp = api.create_review_request(
        env["campaign"]["id"], {"contact_id": env["contact"]["id"]}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_FREQUENCY_CAP_ACTIVE.value)

    assert read_campaign(env["campaign"]["id"])["credits_reserved"] == 1


def test_enqueue_at_exactly_the_cooldown_end_is_allowed(api, admin_headers):
    """PRD §3.6: "An enqueue is rejected with `ERR_FREQUENCY_CAP_ACTIVE` (409) whenever the
    current logical instant is at or after the anchor and strictly before the anchor plus
    the cap; an enqueue at *exactly* the anchor plus the cap is allowed, because the
    interval's end is exclusive."
    PRD §3.6: "On success, one credit is reserved (`credits_reserved` rises by one), the
    contact's `last_requested_at` is stamped with the current logical instant and its
    `request_count` rises by one."

    Design: Difficulty/resource_temporal_overlap/contact_frequency_cap_half_open_window_rejects_then_allows_at_exact_end
    """
    env = _setup_contact_with_one_request_at_the_clock_start()

    set_clock("2026-05-31T00:00:00Z")
    second = validate_success(
        api.create_review_request(
            env["campaign"]["id"], {"contact_id": env["contact"]["id"]}, admin_headers
        ),
        201,
    )
    assert_review_request(second)
    assert second["status"] == "QUEUED"

    contacts = validate_success(api.list_contacts(env["business"]["id"], admin_headers))
    contact = [row for row in contacts if row["id"] == env["contact"]["id"]][0]
    assert contact["request_count"] == 2
    assert_instant_equals(
        contact["last_requested_at"], "2026-05-31T00:00:00Z", "Contact.last_requested_at"
    )

    assert read_campaign(env["campaign"]["id"])["credits_reserved"] == 2


# ---------------------------------------------------------------------------
# Enqueue / cancel conserves spendable credits
# ---------------------------------------------------------------------------
def test_enqueue_reserves_one_credit_and_cancel_gives_it_back(api, admin_headers):
    """PRD §3.6: "**Cancelling** a `QUEUED` request takes it to `SUPPRESSED` and is the
    compensating action for the enqueue: `credits_reserved` falls by one and
    `credits_released` rises by one, so that the conserved quantity — allocated less
    reserved less consumed — returns to exactly its pre-enqueue value."

    Design: Difficulty/compensating_invariant/campaign_spendable_credits_conserved_on_enqueue_then_cancel
    """
    env = setup_running_email_campaign(num_contacts=1, credits_allocated=5)
    campaign_id = env["campaign"]["id"]

    request = enqueue_request(campaign_id, env["contacts"][0]["id"])
    after_enqueue = read_campaign(campaign_id)
    assert after_enqueue["credits_reserved"] == 1
    assert_spendable_credits(after_enqueue, 4)

    cancelled = validate_success(api.cancel_review_request(request["id"], admin_headers))
    assert cancelled["status"] == "SUPPRESSED"

    after_cancel = read_campaign(campaign_id)
    assert_credit_ledger(after_cancel, reserved=0, consumed=0, released=1)
    assert_spendable_credits(after_cancel, 5)

    metrics = validate_success(api.get_campaign_metrics(campaign_id, admin_headers))
    assert metrics["credits_available"] == 5
    assert abs(float(metrics["billing_cost"])) < 0.001


def test_cancelling_a_request_does_not_roll_back_the_contact_cooldown_anchor(api, admin_headers):
    """PRD §3.6: "The contact's `last_requested_at` is deliberately **not** rolled back: the
    frequency-cap window survives cancellation, so a cancelled request still burns the
    contact's cooldown."

    Design: Difficulty/compensating_invariant/campaign_spendable_credits_conserved_on_enqueue_then_cancel
    """
    env = setup_running_email_campaign(num_contacts=1, credits_allocated=5)
    contact = env["contacts"][0]

    request = enqueue_request(env["campaign"]["id"], contact["id"])
    validate_success(api.cancel_review_request(request["id"], admin_headers))

    assert read_review_request(request["id"])["status"] == "SUPPRESSED"

    contacts = validate_success(api.list_contacts(env["business"]["id"], admin_headers))
    reread = [row for row in contacts if row["id"] == contact["id"]][0]
    assert_instant_equals(
        reread["last_requested_at"], "2026-05-01T00:00:00Z", "Contact.last_requested_at"
    )
    assert reread["request_count"] == 1


# ---------------------------------------------------------------------------
# Credit availability
# ---------------------------------------------------------------------------
def test_enqueue_without_a_spendable_credit_is_rejected(api, admin_headers):
    """PRD §3.6: "Third, **credit availability**. The campaign's `credits_allocated`, less
    its `credits_reserved`, less its `credits_consumed`, must leave at least 1 credit free.
    If it does not, the enqueue is rejected with `ERR_INSUFFICIENT_CREDITS` (402)."

    Design: Corner/validations/enqueue_without_spendable_credits_returns_insufficient_credits
    """
    env = setup_running_email_campaign(
        num_contacts=2, sites=("GOOGLE",), name="Thin Budget",
        daily_send_cap=5, credits_allocated=1,
    )
    campaign_id = env["campaign"]["id"]
    enqueue_request(campaign_id, env["contacts"][0]["id"])

    resp = api.create_review_request(
        campaign_id, {"contact_id": env["contacts"][1]["id"]}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS.value)

    campaign = read_campaign(campaign_id)
    assert campaign["credits_reserved"] == 1
    assert_spendable_credits(campaign, 0)

    contacts = validate_success(api.list_contacts(env["business"]["id"], admin_headers))
    second = [row for row in contacts if row["id"] == env["contacts"][1]["id"]][0]
    assert second["request_count"] == 0
