"""Queue B corner tests: RBAC denials, participant ownership, segregation of duties."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    make_provider_ops_headers,
    make_fiduciary_reviewer_headers,
    setup_elected_case,
    setup_notified_case,
    setup_ira_with_fee_disclosure,
    setup_reconciled_batch,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


def test_fiduciary_cannot_execute_batch():
    """PRD §4: the execute row of the endpoint table authorizes only `ProviderOps`.
    PRD §2.1: "A caller whose role is not on the endpoint's authorized list is rejected
    with `ERR_FORBIDDEN_ROLE`."
    PRD §3.3: "New batches start `OPEN` with `executed_by_user_id`, `locked_at`,
    `executed_at`, and `reconciled_at` all null."

    Design: Corner/rbac/fiduciary_cannot_execute_batch
    """
    ctx = setup_elected_case(balance=300000, election_type="SAFE_HARBOR_IRA")
    res = api_client.execute_distribution_batch(
        ctx["batch"]["id"], make_fiduciary_reviewer_headers("fid_rev_1"))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    batch = get_success_data(
        api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
    assert batch["batch_status"] == "LOCKED"
    assert batch["executed_by_user_id"] is None


def test_plansponsor_cannot_assess_fee():
    """PRD §4: the assess-fee row of the endpoint table authorizes only `ProviderOps`.
    PRD §2.1: "A caller whose role is not on the endpoint's authorized list is rejected
    with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/plansponsor_cannot_assess_fee
    """
    ctx = setup_ira_with_fee_disclosure(balance=300000)
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", OPS))
    res = api_client.assess_ira_fee(ctx["ira"]["id"], SPONSOR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    _, meta = validate_paginated(api_client.list_fee_assessments(
        OPS, params={"safe_harbor_ira_id": ctx["ira"]["id"]}))
    assert meta["total_count"] == 0


def test_participant_cannot_touch_foreign_case():
    """PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the
    acting `Participant` record; ownership checks on any resource that references a
    participant — submitting or voiding an election, closing an IRA, patching a
    participant's own address — compare the resource's `participant_id` (or, for the
    participant record itself, its own `id`) against `X-User-ID`, and a mismatch is
    rejected with `ERR_PARTICIPANT_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/participant_cannot_touch_foreign_case
    """
    ctx = setup_notified_case(balance=50000)
    other = get_success_data(api_client.create_participant(
        {"ssn_hash": "hash-b", "full_name": "Bob B",
         "date_of_birth": "1981-02-02", "mailing_address_line1": "2 Main St",
         "mailing_city": "Springfield", "mailing_state": "IL",
         "mailing_zip": "62701"}, SPONSOR))
    case = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    res = api_client.create_election(
        case["id"],
        {"election_type": "LUMP_SUM_CASH",
         "expected_case_version": case["version"]},
        make_participant_headers(other["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PARTICIPANT_OWNERSHIP_MISMATCH, 403)
    case_after = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    assert case_after["case_status"] == "NOTIFIED"
    _, meta = validate_paginated(api_client.list_elections(
        OPS, params={"distribution_case_id": ctx["case"]["id"]}))
    assert meta["total_count"] == 0


def test_segregation_of_duties_same_user_blocked():
    """PRD §2.1: "The `FiduciaryReviewer` who opens a review of a batch must not be the
    operator who executed that batch; the check compares the reviewer's `X-User-ID` to the
    batch's `executed_by_user_id` and rejects equality with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "The new review copies `plan_id` from the batch, records the caller as
    `reviewer_user_id`, and opens in `OPEN` with `findings_count` zero and `attested_at`
    null."

    Design: Corner/rbac/segregation_of_duties_same_user_blocked
    """
    ctx = setup_reconciled_batch()  # executed_by_user_id == "ops_exec_1"
    res = api_client.create_fiduciary_review(
        {"distribution_batch_id": ctx["batch"]["id"],
         "period_start": "2026-08-01T00:00:00Z",
         "period_end": "2026-09-01T00:00:00Z"},
        make_fiduciary_reviewer_headers("ops_exec_1"),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)

    review = validate_success(api_client.create_fiduciary_review(
        {"distribution_batch_id": ctx["batch"]["id"],
         "period_start": "2026-08-01T00:00:00Z",
         "period_end": "2026-09-01T00:00:00Z"},
        make_fiduciary_reviewer_headers("fid_rev_1"),
    ), 201)
    assert review["reviewer_user_id"] == "fid_rev_1"
