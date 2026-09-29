"""Rate-card windows may touch at an edge but never share a day."""

import pytest

from test_helpers import (
    BROKER_ADMIN_HEADERS,
    AgreementStatus,
    ApiErrorId,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_version_unchanged

INCUMBENT_START = "2026-01-01"
INCUMBENT_END = "2026-09-01"


def draft_agreement(api, principal_id, retailer_id, start, end, base_bps):
    return fixtures.create_agreement(
        api,
        principal_id,
        retailer_id,
        activate=False,
        effective_start_date=start,
        effective_end_date=end,
        base_commission_bps=base_bps,
    )


def activate(api, agreement_id):
    return api.activate_agreement(agreement_id, BROKER_ADMIN_HEADERS)


def read_agreement(api, agreement_id):
    return get_success_data(api.get_agreement(agreement_id, BROKER_ADMIN_HEADERS), 200)


@pytest.fixture
def one_active_card_and_three_drafts(api):
    """An incumbent covering [2026-01-01, 2026-09-01) plus three candidate successors.

    The drafts are, in order, exactly adjacent above the incumbent, overlapping it
    by a single day, and exactly adjacent below it.
    """
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.create_principal(api)
    incumbent = fixtures.create_agreement(
        api,
        principal["id"],
        retailer["id"],
        effective_start_date=INCUMBENT_START,
        effective_end_date=INCUMBENT_END,
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "incumbent": incumbent,
        "adjacent_above": draft_agreement(
            api, principal["id"], retailer["id"], INCUMBENT_END, "2027-01-01", 480
        ),
        "overlapping": draft_agreement(
            api, principal["id"], retailer["id"], "2026-08-31", "2027-06-01", 460
        ),
        "adjacent_below": draft_agreement(
            api, principal["id"], retailer["id"], "2025-06-01", INCUMBENT_START, 520
        ),
    }


class TestAgreementWindowAdjacency:
    def test_a_window_starting_on_the_incumbent_end_date_activates(
        self, api, one_active_card_and_three_drafts
    ):
        """new.start equals other.end, so the strict-inequality overlap test is not met.

        PRD: "Because the windows are half-open, exact adjacency is legal: a new window whose
        `effective_start_date` equals the existing window's `effective_end_date` activates
        cleanly."

        Design: Difficulty/resource_temporal_overlap/commission_agreement_half_open_window_adjacency_versus_one_day_overlap
        """
        activated = get_success_data(
            activate(api, one_active_card_and_three_drafts["adjacent_above"]["id"]), 200
        )

        assert activated["status"] == AgreementStatus.ACTIVE
        assert activated["effective_start_date"] == INCUMBENT_END
        assert activated["activated_at"] is not None

    def test_a_single_shared_day_is_a_window_overlap(
        self, api, one_active_card_and_three_drafts
    ):
        """One day of true intersection is enough to refuse the activation.

        PRD: "Moving an agreement `DRAFT` → `ACTIVE` is rejected when another `ACTIVE` agreement
        for the same principal, retail chain and category has a coverage window that overlaps
        the new one: the violation condition is that the new agreement's `effective_start_date`
        is earlier than the other agreement's `effective_end_date` *and* the other agreement's
        `effective_start_date` is earlier than the new agreement's `effective_end_date`, reported
        as `ERR_AGREEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/commission_agreement_half_open_window_adjacency_versus_one_day_overlap
        """
        response = activate(api, one_active_card_and_three_drafts["overlapping"]["id"])

        validate_error(response, ApiErrorId.AGREEMENT_WINDOW_OVERLAP, 409)
        blocked = read_agreement(api, one_active_card_and_three_drafts["overlapping"]["id"])
        assert blocked["status"] == AgreementStatus.DRAFT
        assert blocked["activated_at"] is None

    def test_adjacency_is_legal_on_the_lower_edge_too(
        self, api, one_active_card_and_three_drafts
    ):
        """Three cards end up tiling the calendar with neither gap nor overlap.

        PRD: "A `BrokerAdmin` drafts one against a `principal_id`, a `retailer_id` and a
        `category_code`, with a half-open coverage window running from `effective_start_date`
        inclusive to `effective_end_date` exclusive — the end date must be later than the start
        date."

        Design: Difficulty/resource_temporal_overlap/commission_agreement_half_open_window_adjacency_versus_one_day_overlap
        """
        above = get_success_data(
            activate(api, one_active_card_and_three_drafts["adjacent_above"]["id"]), 200
        )
        below = get_success_data(
            activate(api, one_active_card_and_three_drafts["adjacent_below"]["id"]), 200
        )

        assert below["status"] == AgreementStatus.ACTIVE
        assert below["effective_end_date"] == INCUMBENT_START
        assert above["effective_start_date"] == INCUMBENT_END

        incumbent = read_agreement(api, one_active_card_and_three_drafts["incumbent"]["id"])
        assert incumbent["status"] == AgreementStatus.ACTIVE
        assert incumbent["effective_start_date"] == INCUMBENT_START
        assert incumbent["effective_end_date"] == INCUMBENT_END

    def test_a_terminated_incumbent_leaves_the_overlap_set(
        self, api, one_active_card_and_three_drafts
    ):
        """The same activation flips from refused to accepted once the incumbents retire.

        PRD: "Termination moves an agreement `ACTIVE` → `TERMINATED`, and is blocked while any
        slotting deal for the same principal, chain and category is still live in `PROPOSED` or
        `COUNTERED` — the rejection is `ERR_AGREEMENT_HAS_OPEN_NEGOTIATION`, on the principle
        that a broker may not pull the rate card out from under an offer that is on the table."

        Design: Difficulty/resource_temporal_overlap/commission_agreement_half_open_window_adjacency_versus_one_day_overlap
        """
        scope = one_active_card_and_three_drafts
        validate_error(
            activate(api, scope["overlapping"]["id"]), ApiErrorId.AGREEMENT_WINDOW_OVERLAP, 409
        )

        terminated = get_success_data(
            api.terminate_agreement(scope["incumbent"]["id"], BROKER_ADMIN_HEADERS), 200
        )
        assert terminated["status"] == AgreementStatus.TERMINATED

        activated = get_success_data(activate(api, scope["overlapping"]["id"]), 200)
        assert activated["status"] == AgreementStatus.ACTIVE

    def test_drafting_never_checks_and_a_failed_activation_mutates_nothing(
        self, api, one_active_card_and_three_drafts
    ):
        """Overlapping drafts sit side by side; the refused activation touches no live card.

        PRD: "A drafted agreement begins with `status` at `DRAFT` and `activated_at` null, and
        no overlap check is performed at draft time — a broker may prepare as many overlapping
        drafts as it likes."

        Design: Difficulty/resource_temporal_overlap/commission_agreement_half_open_window_adjacency_versus_one_day_overlap
        """
        scope = one_active_card_and_three_drafts
        assert scope["overlapping"]["status"] == AgreementStatus.DRAFT
        assert scope["overlapping"]["activated_at"] is None

        another_overlapping_draft = get_success_data(
            api.create_agreement(
                F.agreement_payload(
                    scope["principal"]["id"],
                    scope["retailer"]["id"],
                    effective_start_date="2026-02-01",
                    effective_end_date="2026-10-01",
                    base_commission_bps=440,
                ),
                BROKER_ADMIN_HEADERS,
            ),
            201,
        )
        assert another_overlapping_draft["status"] == AgreementStatus.DRAFT

        before = read_agreement(api, scope["incumbent"]["id"])
        activate(api, scope["overlapping"]["id"])
        after = read_agreement(api, scope["incumbent"]["id"])

        assert after["status"] == AgreementStatus.ACTIVE
        assert_version_unchanged(before, after)
