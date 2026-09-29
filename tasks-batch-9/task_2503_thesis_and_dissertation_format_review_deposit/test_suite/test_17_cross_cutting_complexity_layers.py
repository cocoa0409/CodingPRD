"""Optimistic concurrency on the parent thesis, derived-counter reconciliation and fees.

These are the layers that only show up when several mechanisms run against the same
row in sequence, so each test drives the sequence and reads the intermediate value
after every step rather than only at the end.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant
from test_helpers.factories import (
    create_embargo_request_payload,
    create_permission_record_payload,
    create_repository_deposit_payload,
)
from test_helpers.test_users import ANALYST_ONE_USER_ID, TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]

FIGURE_LETTER = "https://repo.u.edu/permissions/fig-12.pdf"
TABLE_LETTER = "https://repo.u.edu/permissions/tbl-33.pdf"


def test_a_replayed_version_token_cannot_document_a_second_permission_record(
    api: ApiClient,
) -> None:
    """Nothing else blocks the second create, so the stale token is the only failure.

    PRD §2.6: "A `POST /graduate-school/permission-records` request likewise requires the non-optional input field `expected_thesis_version` carrying the client's last observed `version` of the target `Thesis`, and a value that does not equal the thesis's current `version` is rejected with `ERR_STALE_THESIS_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_thesis_version_on_a_permission_record_create_rejected
    """
    world = fx.setup_draft_thesis(
        thesis_overrides={"title": "Stale Dossier", "third_party_item_count": 2}
    )
    thesis_id = world["thesis"]["id"]
    stale_version = fx.thesis_version(thesis_id)

    first = get_success_data(
        api.create_permission_record(
            create_permission_record_payload(
                thesis_id,
                stale_version,
                material_type="FIGURE",
                rights_basis="WRITTEN_PERMISSION",
                page_reference="p. 12",
                document_uri=FIGURE_LETTER,
            ),
            world["student_headers"],
        ),
        201,
    )
    assert first["status"] == "SUBMITTED"

    second_body = create_permission_record_payload(
        thesis_id,
        stale_version,
        material_type="TABLE",
        rights_basis="OPEN_LICENSE",
        page_reference="p. 33",
    )
    validate_error(
        api.create_permission_record(second_body, world["student_headers"]),
        "ERR_STALE_THESIS_VERSION",
        412,
    )
    assert (
        len(get_success_data(api.list_thesis_permission_records(thesis_id, REGISTRAR)))
        == 1
    )

    second_body["expected_thesis_version"] = fx.thesis_version(thesis_id)
    second = get_success_data(
        api.create_permission_record(second_body, world["student_headers"]), 201
    )
    assert second["rights_basis"] == "OPEN_LICENSE"

    assert (
        len(get_success_data(api.list_thesis_permission_records(thesis_id, REGISTRAR)))
        == 2
    )
    assert (
        get_success_data(api.get_thesis(thesis_id, REGISTRAR))[
            "documented_permission_count"
        ]
        == 0
    )


def test_the_parent_version_advances_on_the_child_create_and_on_the_review(
    api: ApiClient,
) -> None:
    """1, 2, 3, 4 — the guarded create and the cascade that recomputes the count both count.

    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly one on every mutation of that row, whether the mutation was requested directly or fell out of a cascade."

    PRD §2.6: "Both guarded creates increment the parent `Thesis.version` by one on success, which is precisely why a client that fires two of them back to back must re-read the thesis in between."

    Design: Corner/cross_cutting_complexity_layers/thesis_version_advances_on_every_accepted_write_against_the_row
    """
    world = fx.setup_draft_thesis(
        thesis_overrides={"title": "Version Ladder", "third_party_item_count": 2}
    )
    thesis_id = world["thesis"]["id"]
    assert world["thesis"]["version"] == 1
    assert fx.thesis_version(thesis_id) == 1

    record = get_success_data(
        api.create_permission_record(
            create_permission_record_payload(
                thesis_id,
                1,
                material_type="EXCERPT",
                rights_basis="FAIR_USE_ASSERTION",
                page_reference="pp. 8-9",
                excerpt_word_count=120,
            ),
            world["student_headers"],
        ),
        201,
    )
    assert fx.thesis_version(thesis_id) == 2

    reviewed = get_success_data(
        api.review_permission_record(
            record["id"],
            {
                "decision": "ACCEPT",
                "review_note": "Fair use asserted within the word limit.",
            },
            ANALYST_ONE,
        ),
        200,
    )
    assert reviewed["status"] == "ACCEPTED"
    assert fx.thesis_version(thesis_id) == 3

    second = get_success_data(
        api.create_permission_record(
            create_permission_record_payload(
                thesis_id,
                3,
                material_type="DATASET",
                rights_basis="PUBLIC_DOMAIN",
                page_reference="appendix B",
            ),
            world["student_headers"],
        ),
        201,
    )
    assert second["status"] == "SUBMITTED"

    thesis = get_success_data(api.get_thesis(thesis_id, REGISTRAR))
    assert thesis["version"] == 4
    assert thesis["documented_permission_count"] == 1


def test_the_documented_count_tracks_membership_of_accepted_and_waived(
    api: ApiClient,
) -> None:
    """0, 1, 1, 2, 3 — a DEFICIENT ruling adds nothing until it is later accepted.

    PRD §3.5: "Every ruling captures the acting analyst's `X-User-ID` as `reviewed_by_user_id`, then recomputes the document's `documented_permission_count` — the count of its permission records whose `status` is `ACCEPTED` or `WAIVED`, so a `DEFICIENT` record contributes nothing and a `WAIVED` one counts as fully documented — and recomputes clearance."

    Design: Corner/cross_cutting_complexity_layers/documented_permission_count_reconciles_after_each_review_decision
    """
    world = fx.setup_draft_thesis(
        thesis_overrides={"title": "Permission Ledger", "third_party_item_count": 2}
    )
    thesis_id = world["thesis"]["id"]
    first = fx.document_permission(
        world,
        material_type="FIGURE",
        rights_basis="WRITTEN_PERMISSION",
        page_reference="p. 12",
        document_uri=FIGURE_LETTER,
    )
    second = fx.document_permission(
        world,
        material_type="TABLE",
        rights_basis="WRITTEN_PERMISSION",
        page_reference="p. 33",
        document_uri=TABLE_LETTER,
    )
    third = fx.document_permission(
        world,
        material_type="DATASET",
        rights_basis="OPEN_LICENSE",
        page_reference="appendix A",
    )

    def documented_count() -> int:
        return get_success_data(api.get_thesis(thesis_id, REGISTRAR))[
            "documented_permission_count"
        ]

    assert documented_count() == 0

    fx.review_permission(world, first, decision="ACCEPT", review_note="Letter on file.")
    assert documented_count() == 1

    deficient = fx.review_permission(
        world,
        second,
        decision="DEFICIENT",
        review_note="The letter does not name the figure.",
    )
    assert deficient["status"] == "DEFICIENT"
    assert documented_count() == 1

    waived = fx.review_permission(
        world, third, decision="WAIVE", review_note="Open licence needs no letter."
    )
    assert waived["status"] == "WAIVED"
    assert documented_count() == 2

    corrected = get_success_data(
        api.review_permission_record(
            second["id"],
            {"decision": "ACCEPT", "review_note": "Corrected letter received."},
            ANALYST_ONE,
        ),
        200,
    )
    assert corrected["status"] == "ACCEPTED"
    assert corrected["reviewed_by_user_id"] == ANALYST_ONE_USER_ID
    assert documented_count() == 3
    assert (
        len(get_success_data(api.list_thesis_permission_records(thesis_id, REGISTRAR)))
        == 3
    )


def test_a_replayed_version_token_cannot_bury_an_unseen_embargo_request(
    api: ApiClient,
) -> None:
    """The stale create is refused; the re-read one supersedes the request it did see.

    PRD §2.6: "A `POST /graduate-school/embargo-requests` request requires the non-optional input field `expected_thesis_version`, carrying the client's last observed `version` of the target `Thesis`. If that value does not equal the thesis's current `version`, the request is rejected with `ERR_STALE_THESIS_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_thesis_version_on_an_embargo_request_create_rejected
    """
    world = fx.setup_passed_defense(thesis_overrides={"title": "Stale Embargo"})
    thesis_id = world["thesis"]["id"]
    stale_version = fx.thesis_version(thesis_id)

    first = get_success_data(
        api.create_embargo_request(
            create_embargo_request_payload(
                thesis_id,
                stale_version,
                reason_code="PUBLISHER_AGREEMENT",
                requested_months=6,
                justification="Six-month publisher hold.",
            ),
            world["student_headers"],
        ),
        201,
    )
    assert first["status"] == "REQUESTED"

    replacement = create_embargo_request_payload(
        thesis_id,
        stale_version,
        reason_code="SENSITIVE_DATA",
        requested_months=12,
        justification="Interview transcripts need longer protection.",
    )
    validate_error(
        api.create_embargo_request(replacement, world["student_headers"]),
        "ERR_STALE_THESIS_VERSION",
        412,
    )
    assert (
        len(get_success_data(api.list_thesis_embargo_requests(thesis_id, REGISTRAR)))
        == 1
    )
    assert (
        get_success_data(api.get_embargo_request(first["id"], REGISTRAR))["status"]
        == "REQUESTED"
    )

    replacement["expected_thesis_version"] = fx.thesis_version(thesis_id)
    second = get_success_data(
        api.create_embargo_request(replacement, world["student_headers"]), 201
    )
    assert second["status"] == "REQUESTED"
    assert second["requested_months"] == 12

    assert (
        get_success_data(api.get_embargo_request(first["id"], REGISTRAR))["status"]
        == "SUPERSEDED"
    )
    assert (
        len(get_success_data(api.list_thesis_embargo_requests(thesis_id, REGISTRAR)))
        == 2
    )


def test_a_five_day_turnaround_earns_nothing_and_one_late_day_costs_2500_cents(
    api: ApiClient,
) -> None:
    """Below the mid tier the deadline does not move, and the readiness read agrees.

    PRD §3.8: "Second, a grace allowance is selected from it: 5 business days when the total is at least 15 business days, otherwise 3 business days when the total is at least 10 business days, otherwise none."

    PRD §3.8: "Sixth, the fee is the chargeable days multiplied by 2,500 cents per day, capped at 50,000 cents, which is reached at twenty chargeable days."

    Design: Corner/cross_cutting_complexity_layers/turnaround_below_the_mid_tier_earns_no_grace_business_days
    """
    world = fx.setup_format_accepted_thesis(
        cycle_clock="2026-10-05T09:00:00Z",
        similarity_pct=5.0,
        excluded_quoted_pct=None,
        decision_clock="2026-10-12T09:00:00Z",
        thesis_overrides={"title": "No Grace Earned"},
    )
    thesis_id = world["thesis"]["id"]

    review = get_success_data(
        api.get_format_review(world["format_review"]["id"], REGISTRAR)
    )
    assert review["turnaround_bdays"] == 5
    assert (
        get_success_data(api.get_thesis(thesis_id, REGISTRAR))[
            "analyst_turnaround_bdays_total"
        ]
        == 5
    )

    fx.set_clock("2026-12-07T10:00:00Z")
    readiness = get_success_data(api.get_deposit_readiness(thesis_id, ANALYST_TWO), 200)
    assert readiness["projected_late_fee_cents"] == 2500

    deposit = get_success_data(
        api.create_repository_deposit(
            create_repository_deposit_payload(
                thesis_id,
                abstract_word_count=150,
                subject_keywords=["a", "b", "c"],
                late_fee_paid_cents=2500,
                advisor_name="Cara Cho",
                department_code="CS",
            ),
            ANALYST_TWO,
        ),
        201,
    )
    assert deposit["late_fee_cents"] == 2500
    assert_instant(deposit["deposited_at"], "2026-12-07T10:00:00Z", "deposited_at")
    assert deposit["access_level"] == "OPEN_ACCESS"
    assert deposit["embargo_release_date"] is None

    assert (
        get_success_data(api.get_thesis(thesis_id, REGISTRAR))["workflow_state"]
        == "DEPOSITED"
    )
