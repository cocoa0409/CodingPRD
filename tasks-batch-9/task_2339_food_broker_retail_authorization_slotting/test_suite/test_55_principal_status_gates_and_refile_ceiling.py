"""Two admissible status sets for one error id, and a deny/refile loop bounded at two."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    AUDIT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    ApiErrorId,
    CatalogState,
    DeductionReasonCode,
    DeductionSettlementState,
    DisputeState,
    PresentationStatus,
    PrincipalStatus,
    UPC_1,
    UPC_2,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers import factories as F

AMOUNT_CENTS = 60000


@pytest.fixture
def prospect_principal_with_a_draft_deck(api):
    """The principal never left PROSPECT, yet its rate card is ACTIVE and its item VALIDATED."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.create_principal(api, slotting_budget_cents=20000000)
    agreement = fixtures.create_agreement(api, principal["id"], retailer["id"])
    item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    review = fixtures.opened_review(api, retailer["id"])
    presentation = fixtures.create_presentation(
        api, review["id"], principal["id"], [item["id"]]
    )
    deduction = fixtures.create_deduction(
        api,
        retailer["id"],
        principal["id"],
        reason_code=DeductionReasonCode.SHORTAGE,
        amount_cents=AMOUNT_CENTS,
        deduction_date="2026-08-01",
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "agreement": agreement,
        "item": item,
        "review": review,
        "presentation": presentation,
        "deduction": deduction,
    }


def set_status(api, principal_id, status):
    return get_success_data(
        api.set_principal_status(
            principal_id, F.principal_status_payload(status), BROKER_ADMIN_HEADERS
        ),
        200,
    )


def suspend_the_principal(api, scope):
    set_status(api, scope["principal"]["id"], PrincipalStatus.ACTIVE)
    return set_status(api, scope["principal"]["id"], PrincipalStatus.SUSPENDED)


def read_deck(api, scope):
    return get_success_data(
        api.get_presentation(scope["presentation"]["id"], ACCOUNT_MANAGER_HEADERS), 200
    )


def read_item(api, item_id):
    return get_success_data(api.get_item(item_id, ACCOUNT_MANAGER_HEADERS), 200)


def attempt_submission(api, scope):
    return api.submit_presentation(scope["presentation"]["id"], ACCOUNT_MANAGER_HEADERS)


def create_second_item(api, scope):
    return get_success_data(
        api.create_item(
            F.item_payload(
                scope["principal"]["id"], upc=UPC_2, description="Frozen Empanadas 10ct"
            ),
            ACCOUNT_MANAGER_HEADERS,
        ),
        201,
    )


def attempt_catalog_submission(api, item_id):
    return api.submit_catalog(
        item_id, F.catalog_submission_payload(upc=UPC_2), ACCOUNT_MANAGER_HEADERS
    )


def file_the_claim(api, scope):
    return fixtures.file_claim(api, scope["deduction"]["id"], AMOUNT_CENTS)


def substantiate_and_deny(api, scope, document_ref, denial_reason):
    fixtures.substantiate(api, scope["deduction"]["id"], document_ref)
    return fixtures.deny_recovery(api, scope["deduction"]["id"], denial_reason)


class TestPrincipalStatusGatesAndRefileCeiling:
    def test_catalog_data_may_be_prepared_while_the_principal_is_still_a_prospect(
        self, api, prospect_principal_with_a_draft_deck
    ):
        """The whole fixture was assembled without ever promoting the principal.

        PRD: "The first submission out of `INCOMPLETE` additionally requires that the owning
        principal's `status` is either `PROSPECT` or `ACTIVE` — catalog data may be prepared before a
        principal is fully activated, but not for a suspended or terminated one, and the rejection is
        `ERR_PRINCIPAL_NOT_ACTIVE`."

        PRD: "The principal lifecycle runs `PROSPECT` → `ACTIVE` ⇄ `SUSPENDED` → `TERMINATED`, driven
        by a `BrokerAdmin` supplying the target `status`."

        Design: Corner/errors/principal_status_gates_and_the_refile_ceiling
        """
        scope = prospect_principal_with_a_draft_deck

        principal = fixtures.get_principal(api, scope["principal"]["id"])

        assert principal["status"] == PrincipalStatus.PROSPECT
        assert scope["item"]["catalog_state"] == CatalogState.VALIDATED
        assert scope["item"]["catalog_submission_round"] == 1

    def test_submitting_a_deck_demands_active_rather_than_merely_prospect(
        self, api, prospect_principal_with_a_draft_deck
    ):
        """Every other submission gate is satisfied; only the principal's own status is not.

        PRD: "First come the state checks: the review must be `OPEN`, otherwise `ERR_REVIEW_NOT_OPEN`,
        and the principal's `status` must be `ACTIVE`, otherwise `ERR_PRINCIPAL_NOT_ACTIVE`."

        PRD: "Submitting the deck moves `status` from `DRAFT` to `SUBMITTED` and is the most heavily
        guarded operation in the system."

        Design: Corner/errors/principal_status_gates_and_the_refile_ceiling
        """
        scope = prospect_principal_with_a_draft_deck

        response = attempt_submission(api, scope)

        validate_error(response, ApiErrorId.PRINCIPAL_NOT_ACTIVE, 409)
        assert read_deck(api, scope)["status"] == PresentationStatus.DRAFT

    def test_promoting_the_principal_unblocks_the_identical_submission(
        self, api, prospect_principal_with_a_draft_deck
    ):
        """The ACTIVE agreement created in setup is exactly what the promotion requires.

        PRD: "Promotion from `PROSPECT` to `ACTIVE` requires that at least one commission agreement for
        this principal has already reached `ACTIVE`; without one the request is rejected with
        `ERR_PRINCIPAL_HAS_NO_AGREEMENT`, and on success `credit_posture` is recomputed."

        Design: Corner/errors/principal_status_gates_and_the_refile_ceiling
        """
        scope = prospect_principal_with_a_draft_deck
        validate_error(attempt_submission(api, scope), ApiErrorId.PRINCIPAL_NOT_ACTIVE, 409)

        promoted = set_status(api, scope["principal"]["id"], PrincipalStatus.ACTIVE)
        submitted = get_success_data(attempt_submission(api, scope), 200)

        assert promoted["status"] == PrincipalStatus.ACTIVE
        assert submitted["status"] == PresentationStatus.SUBMITTED

    def test_item_creation_is_not_gated_on_the_principals_status_at_all(
        self, api, prospect_principal_with_a_draft_deck
    ):
        """A suspended principal may still have new items set up against it.

        PRD: "New item setup belongs to the `BrokerAccountManager`, who creates an item against a
        `principal_id` with a `upc`, a `description` as it will appear on the retailer's item-setup form,
        a `case_pack_units` count of at least one consumer unit per shipping case, a `list_price_cents`
        of at least one cent per case, and a `unit_cost_cents` landed cost of at least one cent per
        case."

        PRD: "A new item begins with `catalog_state` at `INCOMPLETE` and `catalog_submission_round` at
        0, and its five catalog attributes — `gtin14`, `dimensions_cm`, `gross_weight_g`,
        `nutrition_panel_url` and `shelf_life_days` — are all null until the first catalog submission."

        Design: Corner/errors/principal_status_gates_and_the_refile_ceiling
        """
        scope = prospect_principal_with_a_draft_deck
        suspended = suspend_the_principal(api, scope)
        assert suspended["status"] == PrincipalStatus.SUSPENDED

        second_item = create_second_item(api, scope)

        assert second_item["catalog_state"] == CatalogState.INCOMPLETE
        assert second_item["catalog_submission_round"] == 0
        assert second_item["gtin14"] is None

    def test_a_suspended_principal_may_not_load_catalog_data(
        self, api, prospect_principal_with_a_draft_deck
    ):
        """`SUSPENDED` is in neither admissible set, so even the permissive gate refuses it.

        PRD: "Moving `ACTIVE` → `SUSPENDED` carries no precondition, and while suspended the principal's
        presentations may not be submitted and its slotting deals may not be accepted — both attempts
        fail with `ERR_PRINCIPAL_NOT_ACTIVE`."

        PRD: "Whichever state it starts from, an accepted submission persists all five catalog
        attributes onto the item, increments `catalog_submission_round` by one, and clears
        `catalog_reject_reason` to null."

        Design: Corner/errors/principal_status_gates_and_the_refile_ceiling
        """
        scope = prospect_principal_with_a_draft_deck
        suspend_the_principal(api, scope)
        second_item = create_second_item(api, scope)

        response = attempt_catalog_submission(api, second_item["id"])

        validate_error(response, ApiErrorId.PRINCIPAL_NOT_ACTIVE, 409)
        refused = read_item(api, second_item["id"])
        assert refused["catalog_state"] == CatalogState.INCOMPLETE
        assert refused["catalog_submission_round"] == 0

    def test_reinstatement_accepts_the_body_that_was_just_refused(
        self, api, prospect_principal_with_a_draft_deck
    ):
        """Nothing about the payload changed — only the principal's status did.

        PRD: "The reverse move `SUSPENDED` → `ACTIVE` also carries no precondition, recomputes
        `credit_posture`, and may be repeated any number of times: reinstatement is a genuine cycle, not
        a one-shot."

        PRD: "Submission drives `catalog_state` from `INCOMPLETE` to `SUBMITTED`."

        Design: Corner/errors/principal_status_gates_and_the_refile_ceiling
        """
        scope = prospect_principal_with_a_draft_deck
        suspend_the_principal(api, scope)
        second_item = create_second_item(api, scope)
        validate_error(
            attempt_catalog_submission(api, second_item["id"]),
            ApiErrorId.PRINCIPAL_NOT_ACTIVE,
            409,
        )

        set_status(api, scope["principal"]["id"], PrincipalStatus.ACTIVE)
        accepted = get_success_data(attempt_catalog_submission(api, second_item["id"]), 200)

        assert accepted["catalog_state"] == CatalogState.SUBMITTED
        assert accepted["catalog_submission_round"] == 1

    def test_each_refile_increments_the_counter_and_discards_the_old_evidence(
        self, api, prospect_principal_with_a_draft_deck
    ):
        """The initial filing is not a refile, so the counter runs 0, 1, 2 across three filings.

        PRD: "A refile increases `refile_count` by one, resets `substantiation_doc_count` to 0 so
        evidence must be assembled afresh, clears `denial_reason` to null, and records the new
        `filed_by_user_id`."

        PRD: "the first document moves `dispute_state` from `FILED` to `SUBSTANTIATED`, and further
        calls while already `SUBSTANTIATED` are a self-loop that only increments
        `substantiation_doc_count` without changing state"

        Design: Corner/errors/principal_status_gates_and_the_refile_ceiling
        """
        scope = prospect_principal_with_a_draft_deck

        first_filing = file_the_claim(api, scope)
        assert first_filing["dispute_state"] == DisputeState.FILED
        assert first_filing["refile_count"] == 0

        substantiated = fixtures.substantiate(api, scope["deduction"]["id"], "POD-1")
        assert substantiated["dispute_state"] == DisputeState.SUBSTANTIATED
        assert substantiated["substantiation_doc_count"] == 1
        fixtures.deny_recovery(api, scope["deduction"]["id"], "Proof of delivery illegible")

        first_refile = file_the_claim(api, scope)

        assert first_refile["dispute_state"] == DisputeState.FILED
        assert first_refile["refile_count"] == 1
        assert first_refile["substantiation_doc_count"] == 0
        assert first_refile["denial_reason"] is None

        substantiate_and_deny(api, scope, "POD-2", "Still illegible")
        second_refile = file_the_claim(api, scope)

        assert second_refile["refile_count"] == 2
        assert second_refile["substantiation_doc_count"] == 0

    def test_every_denial_is_money_neutral_and_the_third_refile_is_refused(
        self, api, prospect_principal_with_a_draft_deck
    ):
        """Two refiles are spent, so `refile_count` is no longer below the allowance.

        PRD: "A denied claim may be refiled by a `BrokerAccountManager`, moving `dispute_state` from
        `DENIED` back to `FILED` under the same dispute-window and claim-ceiling conditions as an initial
        filing, plus one more: `refile_count` must still be below the two refiles allowed, otherwise
        `ERR_REFILE_LIMIT_REACHED`."

        PRD: "The deny-and-refile round trip is therefore bounded, and it never moves a cent."

        Design: Corner/errors/principal_status_gates_and_the_refile_ceiling
        """
        scope = prospect_principal_with_a_draft_deck
        file_the_claim(api, scope)
        first_denial = substantiate_and_deny(api, scope, "POD-1", "Proof of delivery illegible")
        assert first_denial["dispute_state"] == DisputeState.DENIED
        assert first_denial["open_cents"] == AMOUNT_CENTS
        file_the_claim(api, scope)
        substantiate_and_deny(api, scope, "POD-2", "Still illegible")
        file_the_claim(api, scope)
        final_denial = substantiate_and_deny(api, scope, "POD-3", "Final denial")
        assert final_denial["dispute_state"] == DisputeState.DENIED

        response = api.dispute_deduction(
            scope["deduction"]["id"], F.dispute_payload(AMOUNT_CENTS), ACCOUNT_MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.REFILE_LIMIT_REACHED, 409)

    def test_the_whole_dispute_round_trip_leaves_the_ledger_where_it_started(
        self, api, prospect_principal_with_a_draft_deck
    ):
        """Three filings and three denials later, not a cent has moved.

        PRD: "it moves `dispute_state` from `SUBSTANTIATED` to `DENIED` and records `denial_reason`;
        `settlement_state` stays `OPEN`, `recovered_cents`, `conceded_cents` and `open_cents` are all
        unchanged, and the principal's `open_deduction_cents` does not move."

        PRD: "Denial is the mirror image and is deliberately money-neutral."

        Design: Corner/errors/principal_status_gates_and_the_refile_ceiling
        """
        scope = prospect_principal_with_a_draft_deck
        file_the_claim(api, scope)
        substantiate_and_deny(api, scope, "POD-1", "Proof of delivery illegible")
        file_the_claim(api, scope)
        substantiate_and_deny(api, scope, "POD-2", "Still illegible")
        file_the_claim(api, scope)
        substantiate_and_deny(api, scope, "POD-3", "Final denial")

        final = get_success_data(
            api.get_deduction(scope["deduction"]["id"], AUDIT_MANAGER_HEADERS), 200
        )

        assert final["dispute_state"] == DisputeState.DENIED
        assert final["settlement_state"] == DeductionSettlementState.OPEN
        assert final["open_cents"] == AMOUNT_CENTS
        assert final["recovered_cents"] == 0
        assert final["conceded_cents"] == 0
        assert final["refile_count"] == 2
        assert (
            fixtures.get_principal(api, scope["principal"]["id"])["open_deduction_cents"]
            == AMOUNT_CENTS
        )
