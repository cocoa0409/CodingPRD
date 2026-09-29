"""Two state machines that do not run in a straight line.

A sync request cycles `QUOTED -> REVISION_REQUESTED -> QUOTED`, re-running the
pricing side effect each time round, and then forks out of `ACCEPTED` into two
delivery branches whose guards differ. A composition instead carries two
independent status axes on one row, so infringement work cycles the rights axis
while the catalogue axis stands still, and only retirement writes both at once.
"""

from test_helpers import (
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    assert_cents_equal,
    assert_composition_axes,
    assert_created,
    assert_credit_exposure,
    assert_declared_error,
    assert_ok,
    assert_quote_figures,
    assert_status,
    composition_version,
    new_cataloged_work,
    new_deal_ground,
    new_detected_claim,
    read_claim,
    read_composition,
    read_licensee,
    review_sync_request,
    submit_sync_request,
)
from test_helpers import factories as build

# ---------------------------------------------------------------------------
# The sync-request revision cycle and the fork out of ACCEPTED
# ---------------------------------------------------------------------------

COMPOSER_TERMS = {
    "display_name": "Owen Frey",
    "pro_affiliation": "SESAC",
    "payee_country": "US",
    "tax_withholding_pct": 0.30,
}

AGREEMENT_TERMS = {
    "writer_share_pct": 60.00,
    "publisher_share_pct": 40.00,
    "sync_fee_share_pct": 40.00,
    "buyout_fee_cents": 0,
    "exclusivity": "NON_EXCLUSIVE",
    "holdback_days": 0,
    "advance_cents": 0,
    "blanket_opt_in": True,
}


def _quoted_edit_deal(api):
    """A BROADCAST_TV request asking for a custom edit, stems and two cutdowns.

    The work is `CATALOGED` under an `ACTIVE` royalty-split agreement, the tier
    prices from 300000 cents over a 1-120 month range, the buyer carries a
    5000000 cent credit limit, and the request has been reviewed and quoted for
    a 12 month term.
    """
    deal = new_deal_ground(
        api,
        work_overrides={
            "composer_overrides": dict(COMPOSER_TERMS),
            "agreement_overrides": dict(AGREEMENT_TERMS),
            "title": "Glasshouse",
            "duration_sec": 165,
            "tempo_bpm": 128,
            "genre": "ELECTRONIC",
            "mood_tags": ["QUIRKY", "UPLIFTING"],
            "instrumentation": ["SYNTH"],
        },
        tier_overrides={
            "code": "BTV-STD",
            "media_type": "BROADCAST_TV",
            "allowed_scales": ["LOCAL", "NATIONAL", "WORLDWIDE"],
            "base_rate_cents": 300000,
            "min_term_months": 1,
            "max_term_months": 120,
            "per_use_eligible": True,
            "blanket_eligible": False,
        },
        licensee_overrides={
            "legal_name": "Foxglove Productions",
            "licensee_type": "PRODUCTION_COMPANY",
            "credit_limit_cents": 5000000,
        },
    )
    submit_sync_request(
        api,
        deal,
        media_type="BROADCAST_TV",
        distribution_scale="NATIONAL",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=12,
        exclusive_requested=False,
        custom_edit_requested=True,
        stems_requested=True,
        alternate_lengths_sec=[30, 60],
        rush_requested=False,
        brief_note="need a 30 and a 60 cutdown",
    )
    review_sync_request(api, deal)
    deal.sync_request = assert_ok(
        api.quote_sync_request(deal.sync_request_id, build.quote_payload(14), LICENSING_AGENT)
    )
    return deal


def _request_two_year_revision(api, deal):
    """The owning licensee asks for a two-year term, releasing the reservation."""
    deal.sync_request = assert_ok(
        api.request_sync_revision(
            deal.sync_request_id,
            build.revision_payload("make it two years", revised_term_months=24),
            deal.licensee_headers,
        )
    )
    return deal


def _requote_and_accept(api, deal):
    """Re-price from `REVISION_REQUESTED` and let the licensee accept."""
    deal.sync_request = assert_ok(
        api.quote_sync_request(deal.sync_request_id, build.quote_payload(14), LICENSING_AGENT)
    )
    deal.sync_request = assert_ok(
        api.accept_sync_request(deal.sync_request_id, None, deal.licensee_headers)
    )
    return deal


def _issue_from_accepted(api, deal):
    deal.license = assert_created(
        api.create_license(
            build.per_use_license_payload(
                deal.sync_request_id, composition_version(api, deal.composition_id)
            ),
            LICENSING_AGENT,
        )
    )
    return deal


class TestSyncRequestRevisionCycle:
    def test_revision_returns_the_request_to_an_unpriced_state_and_lifts_the_round(self, api):
        """PRD §3.4: "The transition increments `revision_round` by 1, applies whichever
        revised terms were supplied to the request, clears `quoted_fee_cents`,
        `quoted_spend_basis_cents`, `quoted_discount_pct` and `quote_expires_at` to null,
        and releases the licensee's reservation."

        Design: Difficulty/non_linear_state_machine/sync_request_revision_cycle_then_edit_branch_to_delivery
        """
        deal = _quoted_edit_deal(api)

        assert_status(deal.sync_request, "QUOTED")
        assert deal.sync_request["revision_round"] == 0
        assert_quote_figures(deal.sync_request, 489000, 0.00, 489000)

        _request_two_year_revision(api, deal)

        assert_status(deal.sync_request, "REVISION_REQUESTED")
        assert deal.sync_request["revision_round"] == 1
        assert deal.sync_request["quoted_fee_cents"] is None
        assert deal.sync_request["quoted_spend_basis_cents"] is None
        assert deal.sync_request["quoted_discount_pct"] is None
        assert deal.sync_request["quote_expires_at"] is None
        assert deal.sync_request["requested_term_months"] == 24
        assert_credit_exposure(read_licensee(api, deal.licensee_id), 0, 0, 5000000)

    def test_requote_from_revision_requested_reprices_and_replaces_the_reservation(self, api):
        """PRD §3.4: "Re-quoting from `REVISION_REQUESTED` recomputes the fee from the
        revised term, scale and exclusivity and replaces the reservation on the licensee
        — the old quoted amount comes off and the new one goes on."

        Design: Difficulty/non_linear_state_machine/sync_request_revision_cycle_then_edit_branch_to_delivery
        """
        deal = _quoted_edit_deal(api)
        _request_two_year_revision(api, deal)

        deal.sync_request = assert_ok(
            api.quote_sync_request(deal.sync_request_id, build.quote_payload(14), LICENSING_AGENT)
        )

        assert_status(deal.sync_request, "QUOTED")
        assert deal.sync_request["revision_round"] == 1
        assert_quote_figures(deal.sync_request, 664500, 5.00, 631275)
        assert_credit_exposure(read_licensee(api, deal.licensee_id), 0, 631275, 4368725)


class TestDeliveryForkOutOfAccepted:
    def test_delivery_straight_from_accepted_is_refused_when_an_edit_was_requested(self, api):
        """PRD §3.5: "Arriving straight from `ACCEPTED` is legal only when no edit work
        was ever asked for — `custom_edit_requested` false, `stems_requested` false, and
        `alternate_lengths_sec` empty — and an attempt to skip a requested edit pass is
        refused with `ERR_EDIT_PASS_REQUIRED`; on that path `delivered_asset_count` need
        only be at least 1, and a value below 1 is refused with `ERR_VALIDATION`."

        Design: Difficulty/non_linear_state_machine/sync_request_revision_cycle_then_edit_branch_to_delivery
        """
        deal = _quoted_edit_deal(api)
        _request_two_year_revision(api, deal)
        _requote_and_accept(api, deal)
        _issue_from_accepted(api, deal)

        assert_status(deal.sync_request, "ACCEPTED")
        refused = api.deliver_sync_request(
            deal.sync_request_id,
            build.deliver_payload(4, delivery_note="skipping the edit pass"),
            CATALOG_ADMIN,
        )
        assert_declared_error(refused, "ERR_EDIT_PASS_REQUIRED")

        reread = assert_ok(api.get_sync_request(deal.sync_request_id, LICENSING_AGENT))
        assert_status(reread, "ACCEPTED")

    def test_edit_pass_branch_delivers_the_full_set_on_the_same_input(self, api):
        """PRD §3.5: "Arriving from `EDIT_IN_PROGRESS`, the count must cover the full
        deliverable set: at least 1 for the master, plus 1 more when `stems_requested` is
        true, plus one more for each member of `alternate_lengths_sec`; anything short is
        refused with `ERR_DELIVERABLE_COUNT_SHORT`."

        Design: Difficulty/non_linear_state_machine/sync_request_revision_cycle_then_edit_branch_to_delivery
        """
        deal = _quoted_edit_deal(api)
        _request_two_year_revision(api, deal)
        _requote_and_accept(api, deal)
        _issue_from_accepted(api, deal)

        assert_cents_equal(deal.license["final_fee_cents"], 631275, "final_fee_cents")
        assert deal.license["term_end"].startswith("2028-08-31")

        in_progress = assert_ok(
            api.start_sync_request_edit(
                deal.sync_request_id, {"edit_note": "cutdowns plus stems"}, CATALOG_ADMIN
            )
        )
        assert_status(in_progress, "EDIT_IN_PROGRESS")

        delivered = assert_ok(
            api.deliver_sync_request(
                deal.sync_request_id,
                build.deliver_payload(4, delivery_note="master, stems, 30s, 60s"),
                CATALOG_ADMIN,
            )
        )
        assert_status(delivered, "DELIVERED")
        assert delivered["delivered_asset_count"] == 4
        assert_credit_exposure(read_licensee(api, deal.licensee_id), 631275, 0, 4368725)


# ---------------------------------------------------------------------------
# The two independent status axes of a composition
# ---------------------------------------------------------------------------


def _classical_cataloged_work(api):
    """The catalogued work the claim hangs off, tagged for a classical cue."""
    return new_cataloged_work(
        api,
        composer_overrides={
            "display_name": "Pia Lindqvist",
            "pro_affiliation": "PRS",
            "payee_country": "SE",
            "tax_withholding_pct": 0.15,
        },
        agreement_overrides={
            "writer_share_pct": 50.00,
            "publisher_share_pct": 50.00,
            "sync_fee_share_pct": 40.00,
            "buyout_fee_cents": 0,
            "exclusivity": "NON_EXCLUSIVE",
            "holdback_days": 0,
            "advance_cents": 0,
            "blanket_opt_in": True,
        },
        title="Northern Drift",
        duration_sec=240,
        tempo_bpm=100,
        genre="CLASSICAL",
        mood_tags=["CALM"],
        instrumentation=["STRINGS", "PIANO"],
    )


def _work_with_open_claim(api):
    """A `CATALOGED`, `AVAILABLE` work carrying one claim in `DETECTED`.

    The detection is a 225 second `UGC_VIDEO` match at 99.0 confidence, so the
    claim's exposure is fixed before any axis moves.
    """
    work = _classical_cataloged_work(api)
    match, claim = new_detected_claim(
        api,
        work.composition_id,
        source_platform="UGC_VIDEO",
        source_reference="ugc:northern-drift-lift",
        matched_seconds=225,
        confidence_pct=99.0,
    )
    return work, match, claim


def _serve_notice(api, claim_id):
    return assert_ok(
        api.notice_claim(claim_id, {"notice_channel": "PLATFORM_FORM"}, RIGHTS_MANAGER)
    )


def _settle_statutory(api, claim_id):
    return assert_ok(
        api.settle_claim(
            claim_id,
            build.settle_claim_payload("STATUTORY", payment_received=True),
            RIGHTS_MANAGER,
        )
    )


class TestCompositionAxesMoveIndependently:
    def test_notice_restricts_the_rights_axis_and_leaves_the_catalogue_axis_alone(self, api):
        """PRD §3.8: "Notice also moves the cited work's `availability_status` from
        `AVAILABLE` to `RESTRICTED`, which downweights it in search and blocks exclusive
        issuance on it while the claim stays open."

        Design: Difficulty/non_linear_state_machine/composition_catalog_and_availability_axes_move_independently
        """
        work, _match, claim = _work_with_open_claim(api)
        assert_composition_axes(
            read_composition(api, work.composition_id), "CATALOGED", "AVAILABLE"
        )

        noticed = _serve_notice(api, claim["id"])
        assert_status(noticed, "NOTICED")

        composition = read_composition(api, work.composition_id)
        assert_composition_axes(composition, "CATALOGED", "RESTRICTED")
        assert composition["open_claim_count"] == 1

    def test_metadata_revision_moves_neither_axis(self, api):
        """PRD §3.2: "Neither status axis is ever changed by a metadata revision."

        Design: Difficulty/non_linear_state_machine/composition_catalog_and_availability_axes_move_independently
        """
        work, _match, claim = _work_with_open_claim(api)
        _serve_notice(api, claim["id"])

        revised = assert_ok(
            api.update_composition(
                work.composition_id,
                {"tempo_bpm": 140, "mood_tags": ["CALM", "HOPEFUL"]},
                CATALOG_ADMIN,
            )
        )
        assert revised["tempo_bpm"] == 140
        assert_composition_axes(revised, "CATALOGED", "RESTRICTED")
        assert_composition_axes(
            read_composition(api, work.composition_id), "CATALOGED", "RESTRICTED"
        )

    def test_settlement_closes_the_rights_cycle_back_to_available(self, api):
        """PRD §3.8: "Settlement finally returns the work from `RESTRICTED` to
        `AVAILABLE`, but only once `open_claim_count` has reached 0 — a second open claim
        on the same work keeps it restricted."

        Design: Difficulty/non_linear_state_machine/composition_catalog_and_availability_axes_move_independently
        """
        work, _match, claim = _work_with_open_claim(api)
        _serve_notice(api, claim["id"])
        assert_ok(
            api.update_composition(
                work.composition_id,
                {"tempo_bpm": 140, "mood_tags": ["CALM", "HOPEFUL"]},
                CATALOG_ADMIN,
            )
        )

        settled = _settle_statutory(api, claim["id"])
        assert_status(settled, "SETTLED")
        assert settled["settlement_basis"] == "STATUTORY"
        assert_cents_equal(settled["settlement_amount_cents"], 225000, "settlement_amount_cents")
        assert_cents_equal(settled["settlement_floor_cents"], 67500, "settlement_floor_cents")
        assert_cents_equal(settled["composer_share_cents"], 90000, "composer_share_cents")

        composition = read_composition(api, work.composition_id)
        assert_composition_axes(composition, "CATALOGED", "AVAILABLE")
        assert composition["open_claim_count"] == 0
        assert_status(read_claim(api, claim["id"]), "SETTLED")

    def test_retirement_is_the_one_transition_that_writes_both_axes(self, api):
        """PRD §3.2: "Retirement writes both axes in the same request: `catalog_status`
        becomes `RETIRED` and `availability_status` becomes `WITHDRAWN`."

        Design: Difficulty/non_linear_state_machine/composition_catalog_and_availability_axes_move_independently
        """
        work, _match, claim = _work_with_open_claim(api)
        _serve_notice(api, claim["id"])
        _settle_statutory(api, claim["id"])

        before = read_composition(api, work.composition_id)
        assert_composition_axes(before, "CATALOGED", "AVAILABLE")
        assert before["active_license_count"] == 0

        retired = assert_ok(
            api.retire_composition(
                work.composition_id, {"reason": "catalogue pruning"}, CATALOG_ADMIN
            )
        )
        assert_composition_axes(retired, "RETIRED", "WITHDRAWN")
        assert_composition_axes(
            read_composition(api, work.composition_id), "RETIRED", "WITHDRAWN"
        )
