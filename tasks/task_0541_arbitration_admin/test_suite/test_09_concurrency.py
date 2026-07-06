"""Optimistic concurrency on Case.version for candidate and fee-charge writes."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    add_candidate_payload, create_fee_charge_payload,
)
from test_helpers.fixtures import (
    ADMIN, create_case, create_neutral, add_two_parties, open_selection,
    case_version, get_case, setup_hearing_case_with_paid_deposit,
)

ADM = ADMIN


def test_add_candidate_stale_case_version_returns_stale_version(api):
    """PRD 2.6: "A request that adds a candidate to a case's candidate list must carry
    `expected_case_version` equal to the target case's current `version`. If another writer
    has advanced that `version` since the client last read it ... the add is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/add_candidate_stale_case_version_returns_stale_version
    """
    n1 = create_neutral(api, full_name="N1")
    n2 = create_neutral(api, full_name="N2")
    case = create_case(api, claim_amount_cents=500_000)
    add_two_parties(api, case["id"])
    stale_version = open_selection(api, case["id"])["version"]
    validate_success(api.add_candidate(case["id"], add_candidate_payload(
        neutral_id=n1["id"], expected_case_version=stale_version), ADM), 201)
    resp = api.add_candidate(case["id"], add_candidate_payload(
        neutral_id=n2["id"], expected_case_version=stale_version), ADM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_post_fee_charge_stale_case_version_returns_stale_version(api):
    """PRD 2.6: "A request that posts a neutral fee charge against a case must likewise
    carry `expected_case_version` equal to the case's current `version`. If the version has
    advanced since the client last read the deposit balance, the post is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/post_fee_charge_stale_case_version_returns_stale_version
    """
    ctx = setup_hearing_case_with_paid_deposit(api, deposit_cents=500_000, hourly_rate_cents=50_000)
    stale_version = case_version(api, ctx["case"]["id"])
    validate_success(api.create_fee_charge(ctx["case"]["id"], create_fee_charge_payload(
        neutral_id=ctx["neutral"]["id"], hours=1, expected_case_version=stale_version), ADM), 201)
    resp = api.create_fee_charge(ctx["case"]["id"], create_fee_charge_payload(
        neutral_id=ctx["neutral"]["id"], hours=1, expected_case_version=stale_version), ADM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_candidate_add_increments_case_version(api):
    """PRD 2.4: "`version` — an integer that starts at its initial value and increments by
    one on every mutation." PRD 3.3: "Adding a candidate also increments the case's
    `version`."

    Design: Corner/cross_cutting_complexity_layers/candidate_add_increments_case_version
    """
    n = create_neutral(api)
    case = create_case(api, claim_amount_cents=500_000)
    add_two_parties(api, case["id"])
    v = open_selection(api, case["id"])["version"]
    validate_success(api.add_candidate(case["id"], add_candidate_payload(
        neutral_id=n["id"], expected_case_version=v), ADM), 201)
    assert get_case(api, case["id"])["version"] == v + 1
