"""Scope negotiation: the pinned quoting order, the bounded revision cycle, the
approval cascade that enlarges the contract and thaws frozen sprints, and the
optimistic-concurrency guard on change-request creation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures,
    factories as F,
)

DL = TEST_USERS["delivery_lead_headers"]

TIGHT = {
    "contract_value": 2000.00,
    "budget_hours_cap": 10,
    "standard_hourly_rate": 200.00,
}


def test_third_revision_request_on_a_change_request_is_rejected(api):
    """PRD 3.6: "A change request may be sent back for revision at most **twice**; a third `REQUEST_REVISION` on the same change request — that is, one attempted while `revision_rounds` already stands at 2 — is refused with `ERR_CR_ROUND_LIMIT` (HTTP 409)."

    Design: Corner/validations/third_revision_request_on_change_request_is_rejected
    """
    ctx = fixtures.setup_active_engagement()
    engagement_id = ctx["engagement"]["id"]
    client_headers = ctx["client_headers"]
    cr = fixtures.setup_submitted_change_request(engagement_id, delta_hours=30, rush=False)

    for expected_rounds in (1, 2):
        sent_back = validate_success(
            api.decide_change_request(
                cr["id"], "REQUEST_REVISION", client_headers, note=f"Round {expected_rounds}"
            )
        )
        assert sent_back["revision_rounds"] == expected_rounds
        assert sent_back["status"] == "REVISION_REQUESTED"
        validate_success(api.submit_change_request(cr["id"], DL))

    third = api.decide_change_request(
        cr["id"], "REQUEST_REVISION", client_headers, note="Round 3"
    )
    validate_error(third, ApiErrorId.ERR_CR_ROUND_LIMIT.value)

    after = validate_success(api.get_change_request(cr["id"], DL))
    assert after["revision_rounds"] == 2, "the refused third round does not increment the counter"
    assert after["status"] == "SUBMITTED", "the change request is left where it was"
    engagement = validate_success(api.get_engagement(engagement_id, DL))
    assert engagement["contract_value"] == pytest.approx(100000.00, abs=0.01)


def test_change_request_approval_unfreezes_the_sprint_via_the_new_contract_value(api):
    """PRD 3.6: "Fourth, `budget_posture` is recomputed from that new ratio, and if the engagement drops back to `HEALTHY`, every `ACTIVE` sprint of the engagement has `spend_frozen` set to false."
    PRD 3.6: "Third, the enlarged contract value forces a recomputation of `burn_ratio` — against the **new** `contract_value`, which is why an approval mechanically reduces the burn ratio even though not a single hour has moved."

    Design: Corner/cross_cutting_complexity_layers/change_request_approval_unfreezes_sprints_via_new_contract_value
    """
    ctx = fixtures.setup_with_approved_hours(hours=9.0)  # burn_ratio 0.9 -> AT_RISK, sprint frozen
    engagement_id = ctx["engagement"]["id"]
    assert validate_success(api.get_sprint(ctx["sprint"]["id"], DL))["spend_frozen"] is True

    cr = fixtures.setup_submitted_change_request(engagement_id, delta_hours=30, rush=False)
    assert cr["quoted_amount"] == pytest.approx(6384.00, abs=0.01)

    approved = validate_success(
        api.decide_change_request(cr["id"], "APPROVE", ctx["client_headers"])
    )
    assert approved["status"] == "APPROVED"

    engagement = validate_success(api.get_engagement(engagement_id, DL))
    assert engagement["contract_value"] == pytest.approx(8384.00, abs=0.01), (
        "the quoted amount is added to the contract value"
    )
    assert engagement["budget_hours_cap"] == pytest.approx(40, abs=0.01)
    assert engagement["burn_ratio"] == pytest.approx(0.2147, abs=1e-9), (
        f"1800.00 against the new 8384.00 contract is 0.2147 at 4 decimal places, got "
        f"{engagement['burn_ratio']}"
    )
    assert engagement["budget_posture"] == "HEALTHY"
    assert engagement["approved_hours"] == pytest.approx(9.0, abs=0.01), (
        "the approval changes the denominator, never the burned hours"
    )

    sprint = validate_success(api.get_sprint(ctx["sprint"]["id"], DL))
    assert sprint["spend_frozen"] is False, "the return to HEALTHY thaws the ACTIVE sprint"


def test_change_request_create_with_a_stale_engagement_version_is_rejected(api):
    """PRD 2.7: "Opening a change request requires `expected_engagement_version` in the body, carrying the `version` of the target `Engagement` as the client last observed it. If that number does not equal the engagement's current `version` — because some other writer has advanced the engagement since the read — the create is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412)."
    PRD 3.6: "The change request is created in `DRAFT` with `revision_rounds` at 0 and `quoted_amount` at 0, and — because the engagement's ledger has been touched — the engagement's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_engagement_version_on_change_request_create
    """
    ctx = fixtures.setup_active_engagement()
    engagement_id = ctx["engagement"]["id"]
    observed_version = fixtures.engagement_version(engagement_id, DL)
    fixtures.create_change_request(
        engagement_id,
        delta_hours=10,
        rush=False,
        title="CR one",
        expected_engagement_version=observed_version,
    )

    stale = api.create_change_request(
        F.create_change_request_payload(
            engagement_id=engagement_id,
            title="CR two",
            delta_hours=5,
            rush=False,
            expected_engagement_version=observed_version,
        ),
        DL,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value)

    fresh_version = fixtures.engagement_version(engagement_id, DL)
    assert fresh_version == observed_version + 1, (
        f"the first create bumped the engagement's version from {observed_version} to "
        f"{fresh_version}"
    )

    retried = validate_success(
        api.create_change_request(
            F.create_change_request_payload(
                engagement_id=engagement_id,
                title="CR two",
                delta_hours=5,
                rush=False,
                expected_engagement_version=fresh_version,
            ),
            DL,
        ),
        expected_status=201,
    )
    assert retried["status"] == "DRAFT"

    listed = validate_success(
        api.list_change_requests(DL, params={"engagement_id": engagement_id})
    )
    assert len(listed) == 2, "only the re-read retry is admitted alongside the first"


# ---------------------------------------------------------------------------
# The pinned quoting order
# ---------------------------------------------------------------------------
def test_change_request_quote_tiers_on_the_labour_subtotal_not_the_gross_total(api):
    """PRD 3.6: "**Scope discount tier.** The tier is selected on the labour subtotal alone — never on the final quoted amount, which is larger. A labour subtotal of 20,000.00 or more earns a 10 percent scope discount; a labour subtotal of at least 5,000.00 but below 20,000.00 earns 5 percent; below 5,000.00 there is no discount at all."
    PRD 3.6: "**Quoted amount.** `quoted_amount` is the plain sum of the discounted labour, the overhead and the rush fee. All three are already at 2 decimal places, so no further rounding is applied to the sum."

    Design: Difficulty/combinatorial_formula/change_request_quote_tier_keyed_on_labor_subtotal_mode_c
    """
    ctx = fixtures.setup_active_engagement(
        contract_value=100000.00, budget_hours_cap=500, standard_hourly_rate=200.00
    )
    cr = fixtures.create_change_request(
        ctx["engagement"]["id"],
        delta_hours=95,
        rush=True,
        title="Add multi-currency checkout",
    )

    submitted = validate_success(api.submit_change_request(cr["id"], DL))
    assert submitted["status"] == "SUBMITTED"
    # labour 95 * 200.00 = 19,000.00 -> TIER 5% -> 18,050.00 discounted labour
    # overhead 18,050.00 * 12% = 2,166.00; rush (18,050.00 + 2,166.00) * 15% = 3,032.40
    assert submitted["quoted_amount"] == pytest.approx(23248.40, abs=0.01), (
        f"the 5 percent tier keys on the 19,000.00 labour subtotal, giving 23,248.40; "
        f"got {submitted['quoted_amount']}"
    )
    assert submitted["quoted_amount"] != pytest.approx(22024.80, abs=0.01), (
        "keying the tier on the larger gross figure would wrongly select 10 percent"
    )


def test_change_request_submission_alone_changes_no_scope(api):
    """PRD 3.6: "Quoting happens at submit time, not at draft time, and it re-runs on every re-submit."
    PRD 3.6: "Second, that approval enlarges the engagement: the change request's `quoted_amount` is added to the engagement's `contract_value`, its `delta_hours` is added to the engagement's `budget_hours_cap`, and the engagement's `scope_hours_added` is recomputed as the sum of `delta_hours` across all of that engagement's `APPROVED` change requests."

    Design: Difficulty/combinatorial_formula/change_request_quote_tier_keyed_on_labor_subtotal_mode_c
    """
    ctx = fixtures.setup_active_engagement(
        contract_value=100000.00, budget_hours_cap=500, standard_hourly_rate=200.00
    )
    engagement_id = ctx["engagement"]["id"]
    cr = fixtures.create_change_request(engagement_id, delta_hours=95, rush=True)

    draft = validate_success(api.get_change_request(cr["id"], DL))
    assert draft["quoted_amount"] == 0, "a DRAFT change request is not yet quoted"

    submitted = validate_success(api.submit_change_request(cr["id"], DL))
    assert submitted["quoted_amount"] == pytest.approx(23248.40, abs=0.01)

    engagement = validate_success(api.get_engagement(engagement_id, DL))
    assert engagement["contract_value"] == pytest.approx(100000.00, abs=0.01), (
        "only the client's approval enlarges the contract value"
    )
    assert engagement["budget_hours_cap"] == pytest.approx(500, abs=0.01)


# ---------------------------------------------------------------------------
# The negotiation cycle
# ---------------------------------------------------------------------------
def test_change_request_survives_a_revision_round_and_is_approved(api):
    """PRD 3.6: "An `action` of `REQUEST_REVISION` sends it back: the change request moves `SUBMITTED → REVISION_REQUESTED` and `revision_rounds` increments by 1, opening the negotiation cycle `SUBMITTED → REVISION_REQUESTED → SUBMITTED`."
    PRD 3.6: "**Labour subtotal.** The requested `delta_hours` is multiplied by the engagement's `standard_hourly_rate` as it stands at submit time, and the product is rounded half up to 2 decimal places."

    Design: Difficulty/non_linear_state_machine/change_request_revision_negotiation_cycle_submitted_to_revision_to_submitted
    """
    ctx = fixtures.setup_active_engagement(
        contract_value=100000.00, budget_hours_cap=500, standard_hourly_rate=200.00
    )
    client_headers = ctx["client_headers"]
    cr = fixtures.setup_submitted_change_request(
        ctx["engagement"]["id"], delta_hours=30, rush=False, title="SSO integration"
    )

    sent_back = validate_success(
        api.decide_change_request(
            cr["id"], "REQUEST_REVISION", client_headers, note="Please split the scope"
        )
    )
    assert sent_back["status"] == "REVISION_REQUESTED"
    assert sent_back["revision_rounds"] == 1

    resubmitted = validate_success(api.submit_change_request(cr["id"], DL))
    assert resubmitted["status"] == "SUBMITTED", "the cycle re-enters SUBMITTED"
    # labour 30 * 200.00 = 6,000.00 -> 5% tier -> 5,700.00; overhead 684.00; no rush
    assert resubmitted["quoted_amount"] == pytest.approx(6384.00, abs=0.01), (
        "the re-submit re-runs the quote"
    )

    approved = validate_success(api.decide_change_request(cr["id"], "APPROVE", client_headers))
    assert approved["status"] == "APPROVED"
    assert approved["revision_rounds"] == 1


def test_approved_change_request_enlarges_contract_hours_and_scope(api):
    """PRD 3.6: "Second, that approval enlarges the engagement: the change request's `quoted_amount` is added to the engagement's `contract_value`, its `delta_hours` is added to the engagement's `budget_hours_cap`, and the engagement's `scope_hours_added` is recomputed as the sum of `delta_hours` across all of that engagement's `APPROVED` change requests."

    Design: Difficulty/non_linear_state_machine/change_request_revision_negotiation_cycle_submitted_to_revision_to_submitted
    """
    ctx = fixtures.setup_active_engagement(
        contract_value=100000.00, budget_hours_cap=500, standard_hourly_rate=200.00
    )
    engagement_id = ctx["engagement"]["id"]
    client_headers = ctx["client_headers"]
    cr = fixtures.setup_submitted_change_request(
        engagement_id, delta_hours=30, rush=False, title="SSO integration"
    )
    validate_success(
        api.decide_change_request(cr["id"], "REQUEST_REVISION", client_headers)
    )
    validate_success(api.submit_change_request(cr["id"], DL))
    validate_success(api.decide_change_request(cr["id"], "APPROVE", client_headers))

    engagement = validate_success(api.get_engagement(engagement_id, DL))
    assert engagement["contract_value"] == pytest.approx(106384.00, abs=0.01), (
        f"100,000.00 + the 6,384.00 quote, got {engagement['contract_value']}"
    )
    assert engagement["budget_hours_cap"] == pytest.approx(530, abs=0.01), (
        f"500 + the 30 requested hours, got {engagement['budget_hours_cap']}"
    )
    assert engagement["scope_hours_added"] == pytest.approx(30, abs=0.01)
