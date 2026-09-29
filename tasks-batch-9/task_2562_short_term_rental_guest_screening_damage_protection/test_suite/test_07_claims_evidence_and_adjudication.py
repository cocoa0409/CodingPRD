"""Claim intake, the two-round evidence loop and the requirement schedule."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assertions,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import ADJUDICATOR, PLATFORM_ADMIN


def test_reading_a_claim_that_was_never_stored_is_a_typed_not_found(api):
    """A well-formed id nobody minted resolves to this resource class's 404.

    Path identifiers are resolved before anything else, so an unknown claim id can
    never reach the ownership check that would have produced a 403 — and it must
    never come back as a 200 with an empty body.

    PRD: "Where an identifier does appear in a path it is resolved before the body is examined, and each resource class has its own not-found error: `ERR_GUEST_NOT_FOUND`, `ERR_HOST_NOT_FOUND`, `ERR_JURISDICTION_RULE_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_EVIDENCE_NOT_FOUND`, `ERR_COVERAGE_LAYER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` and `ERR_BLOCKLIST_ENTRY_NOT_FOUND`. All thirteen carry HTTP 404."

    Design: Corner/entities/damage_claim_read_with_unknown_id_returns_not_found
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)

    validate_error(
        api.get_damage_claim(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ApiErrorId.ERR_CLAIM_NOT_FOUND,
        expected_status=404,
    )


def _claim_under_review(api, guest_name, guest_email, claimed_amount_cents=60000):
    """A completed waiver stay carrying one claim that has reached UNDER_REVIEW."""
    cast = fixtures.setup_waiver_listing(
        api, guest_name=guest_name, guest_email=guest_email
    )
    reservation = fixtures.complete_three_night_stay(api, cast)
    claim = fixtures.claim_under_review(
        api, cast, reservation["id"], claimed_amount_cents
    )
    return cast, reservation, claim


def test_the_evidence_loop_is_walked_twice_and_then_refuses_to_reopen(api):
    """Round 2 is the last one; the third reopen attempt is rejected.

    The claim goes out for more evidence once, comes back with genuinely new
    material, and is then asked for more a second time. That request has to fail with
    the round counter still reading 2 and the claim still under review — the loop is
    closed, not merely discouraged.

    PRD: "It is admissible only from `UNDER_REVIEW`, and only while `evidence_round` is below 2; a second attempt to reopen is refused with `ERR_EVIDENCE_ROUNDS_EXHAUSTED`."
    PRD: "The `AWAITING_EVIDENCE` and `UNDER_REVIEW` pair therefore forms a loop that may be traversed at most twice in total, since `evidence_round` may reach 2 but not 3."
    PRD: "A successful submission moves `claim_state` from `AWAITING_EVIDENCE` to `UNDER_REVIEW`, sets `submitted_for_review_at` to the current logical clock reading, and thereby recomputes `adjudication_due_at` as 120 hours — five days — after that instant."

    Design: Difficulty/non_linear_state_machine/damage_claim_evidence_loop_stops_at_max_rounds
    """
    cast, _reservation, claim = _claim_under_review(api, "Ivy Nolan", "ivy@guest.test")
    assertions.assert_fields(
        claim, "damage_claim", claim_state="UNDER_REVIEW", evidence_round=1,
        evidence_count=3,
    )

    reopened = validate_success(
        api.request_claim_evidence(
            claim["id"], ADJUDICATOR, note="Send a wide shot of the whole room."
        )
    )
    assertions.assert_fields(
        reopened,
        "damage_claim",
        claim_state="AWAITING_EVIDENCE",
        evidence_round=2,
        submitted_for_review_at=None,
        adjudication_due_at=None,
    )

    fresh = fixtures.add_photo_evidence(
        api, cast, claim["id"], count=1, prefix="round2-photo"
    )[0]
    assertions.assert_fields(fresh, "claim_evidence", evidence_round=2)

    resubmitted = validate_success(
        api.submit_claim_for_review(claim["id"], cast.host_headers)
    )
    assertions.assert_fields(
        resubmitted,
        "damage_claim",
        claim_state="UNDER_REVIEW",
        evidence_round=2,
        evidence_count=4,
    )

    validate_error(
        api.request_claim_evidence(
            claim["id"], ADJUDICATOR, note="One more angle please."
        ),
        ApiErrorId.ERR_EVIDENCE_ROUNDS_EXHAUSTED,
        expected_status=409,
    )

    held = validate_success(api.get_damage_claim(claim["id"], cast.host_headers))
    assertions.assert_fields(
        held,
        "damage_claim",
        claim_state="UNDER_REVIEW",
        evidence_round=2,
        evidence_count=4,
    )
    assert held["submitted_for_review_at"].startswith("2026-08-13T12:00:00"), (
        "the second submission stamped the clock reading 2026-08-13T12:00:00Z, got "
        "{0!r}".format(held["submitted_for_review_at"])
    )
    assert held["adjudication_due_at"].startswith("2026-08-18T12:00:00"), (
        "120 hours after that submission is 2026-08-18T12:00:00Z, got {0!r}".format(
            held["adjudication_due_at"]
        )
    )

    round_two, _meta = assertions.assert_page(
        api.list_claim_evidence(cast.host_headers, claim_id=claim["id"], evidence_round=2),
        total_count=1,
    )
    assertions.assert_fields(
        round_two[0], "claim_evidence", file_ref="round2-photo-1", evidence_round=2
    )


def test_a_reopened_round_will_not_accept_the_file_set_it_already_rejected(api):
    """Traversing the loop back demands new material, not the same three artifacts.

    The reopen clears the submission stamp and the due date, taking the claim out of
    the service-level sweep, and the freshness clause then blocks a resubmission that
    adds nothing. One round-2 artifact unblocks it, and the claim returns to review
    with its round counter spent.

    PRD: "It moves `claim_state` from `UNDER_REVIEW` back to `AWAITING_EVIDENCE`, increases `evidence_round` by 1 so that subsequent artifacts are stamped with the new round, and clears `submitted_for_review_at` back to null — which makes `adjudication_due_at` null again and takes the claim out of the service-level sweep entirely."
    PRD: "Finally, when `evidence_round` is greater than 1, at least one artifact must carry an `evidence_round` equal to the claim's current `evidence_round`. A reopened round demands genuinely new material; resubmitting the identical file set that was already rejected does not satisfy it."
    PRD: "Any failure is refused with `ERR_EVIDENCE_INCOMPLETE` and nothing about the claim changes."

    Design: Difficulty/non_linear_state_machine/damage_claim_evidence_loop_stops_at_max_rounds
    """
    cast, _reservation, claim = _claim_under_review(api, "Ivy Nolan", "ivy@guest.test")

    reopened = validate_success(
        api.request_claim_evidence(
            claim["id"], ADJUDICATOR, note="Send a wide shot of the whole room."
        )
    )
    assertions.assert_fields(
        reopened,
        "damage_claim",
        claim_state="AWAITING_EVIDENCE",
        evidence_round=2,
        evidence_count=3,
        submitted_for_review_at=None,
        adjudication_due_at=None,
        sla_lapsed=False,
    )
    assertions.assert_version_advanced_by(claim, reopened, 1, "damage_claim")

    validate_error(
        api.submit_claim_for_review(claim["id"], cast.host_headers),
        ApiErrorId.ERR_EVIDENCE_INCOMPLETE,
        expected_status=422,
    )
    untouched = validate_success(api.get_damage_claim(claim["id"], cast.host_headers))
    assertions.assert_fields(
        untouched,
        "damage_claim",
        claim_state="AWAITING_EVIDENCE",
        evidence_round=2,
        evidence_count=3,
        submitted_for_review_at=None,
        adjudication_due_at=None,
    )
    assertions.assert_version_unchanged(reopened, untouched, "damage_claim")

    fixtures.add_photo_evidence(api, cast, claim["id"], count=1, prefix="round2-photo")
    back_under_review = validate_success(
        api.submit_claim_for_review(claim["id"], cast.host_headers)
    )
    assertions.assert_fields(
        back_under_review,
        "damage_claim",
        claim_state="UNDER_REVIEW",
        evidence_round=2,
        evidence_count=4,
    )
    assertions.assert_page(
        api.list_claim_evidence(cast.host_headers, claim_id=claim["id"]), total_count=4
    )


def test_a_claim_of_exactly_fifty_thousand_cents_needs_a_receipt(api):
    """The receipt threshold is inclusive, so the endpoint value itself trips it.

    Two photographs are the universal minimum and would have carried a smaller
    claim. At exactly 50000 the schedule also demands a receipt: the first
    submission is refused and leaves the claim completely untouched, and only once
    the receipt is attached does the claim reach review.

    PRD: "When `claimed_amount_cents` is 50000 cents or more, at least 1 `RECEIPT` is also required. The comparison is inclusive, so a claim of exactly 50000 needs a receipt while a claim of 49999 does not."
    PRD: "Any failure is refused with `ERR_EVIDENCE_INCOMPLETE` and nothing about the claim changes."
    PRD: "It also pins `projected_recovery_cents` by running the settlement waterfall of §3.7 in its **provisional** mode, whose gross loss is the smaller of `claimed_amount_cents` and the listing's `claim_ceiling_cents` — the host's full ask rather than any adjudicated figure."

    Design: Difficulty/boundary_precision_check/receipt_requirement_triggers_at_exactly_fifty_thousand
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Sana Malik", guest_email="sana@guest.test"
    )
    reservation = fixtures.complete_three_night_stay(api, cast)
    claim = fixtures.open_claim(api, cast, reservation["id"], 50000)
    fixtures.add_photo_evidence(api, cast, claim["id"])

    validate_error(
        api.submit_claim_for_review(claim["id"], cast.host_headers),
        ApiErrorId.ERR_EVIDENCE_INCOMPLETE,
        expected_status=422,
    )
    unchanged = validate_success(api.get_damage_claim(claim["id"], cast.host_headers))
    assertions.assert_fields(
        unchanged,
        "damage_claim",
        claim_state="AWAITING_EVIDENCE",
        submitted_for_review_at=None,
        adjudication_due_at=None,
        evidence_count=2,
        evidence_round=1,
    )

    receipt = fixtures.add_receipt_evidence(api, cast, claim["id"], 50000)
    assertions.assert_fields(
        receipt, "claim_evidence", evidence_round=1, amount_cents=50000,
        evidence_type="RECEIPT",
    )

    accepted = validate_success(
        api.submit_claim_for_review(claim["id"], cast.host_headers)
    )
    assertions.assert_fields(
        accepted,
        "damage_claim",
        claim_state="UNDER_REVIEW",
        evidence_count=3,
        evidence_round=1,
        projected_recovery_cents=0,
    )
    assert accepted["submitted_for_review_at"].startswith("2026-08-13T12:00:00"), (
        "submission stamps the logical clock, got {0!r}".format(
            accepted["submitted_for_review_at"]
        )
    )
    assert accepted["adjudication_due_at"].startswith("2026-08-18T12:00:00"), (
        "five days after submission, got {0!r}".format(accepted["adjudication_due_at"])
    )

    artifacts, _meta = assertions.assert_page(
        api.list_claim_evidence(cast.host_headers, claim_id=claim["id"]), total_count=3
    )
    receipts = [row for row in artifacts if row["evidence_type"] == "RECEIPT"]
    assert len(receipts) == 1, (
        "the claim should carry exactly one receipt, got {0}".format(len(receipts))
    )


def test_one_cent_below_the_threshold_two_photographs_are_enough(api):
    """49999 clears review on photographs alone; 50000 on the same set does not.

    Both claims sit on the same finished stay and carry the identical two-photograph
    set, so the only thing that differs between the accepted submission and the
    refused one is a single cent of claimed amount.

    PRD: "At least 2 artifacts of type `PHOTO` are always required."
    PRD: "When `claimed_amount_cents` is 50000 cents or more, at least 1 `RECEIPT` is also required. The comparison is inclusive, so a claim of exactly 50000 needs a receipt while a claim of 49999 does not."
    PRD: "Every artifact of the claim counts toward the per-type minimums regardless of which round stamped it; only the freshness clause above looks at `evidence_round` at all."

    Design: Difficulty/boundary_precision_check/receipt_requirement_triggers_at_exactly_fifty_thousand
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Sana Malik", guest_email="sana@guest.test"
    )
    reservation = fixtures.complete_three_night_stay(api, cast)

    below = fixtures.open_claim(api, cast, reservation["id"], 49999)
    fixtures.add_photo_evidence(api, cast, below["id"], prefix="below-photo")
    cleared = validate_success(
        api.submit_claim_for_review(below["id"], cast.host_headers)
    )
    assertions.assert_fields(
        cleared,
        "damage_claim",
        claimed_amount_cents=49999,
        claim_state="UNDER_REVIEW",
        evidence_count=2,
    )

    at_threshold = fixtures.open_claim(api, cast, reservation["id"], 50000)
    fixtures.add_photo_evidence(api, cast, at_threshold["id"], prefix="edge-photo")
    validate_error(
        api.submit_claim_for_review(at_threshold["id"], cast.host_headers),
        ApiErrorId.ERR_EVIDENCE_INCOMPLETE,
        expected_status=422,
    )
    assertions.assert_fields(
        validate_success(api.get_damage_claim(at_threshold["id"], cast.host_headers)),
        "damage_claim",
        claimed_amount_cents=50000,
        claim_state="AWAITING_EVIDENCE",
        evidence_count=2,
        submitted_for_review_at=None,
    )


def test_an_unfinished_stay_masks_the_ceiling_breach_on_the_same_request(api):
    """One request breaks two gates; the state gate is the one that must answer.

    The ask is 900000 against a 400000 ceiling and the stay has not even been checked
    into, so both the state precondition and the fiscal ceiling are violated. The
    state error has to win, with its own 409 rather than the ceiling's 422, and no
    claim row may survive the attempt.

    PRD: "A claim may only be filed against a reservation whose `stay_state` is `COMPLETED`; anything else is refused with `ERR_STAY_NOT_COMPLETED`."
    PRD: "`claimed_amount_cents` must not exceed the listing's `claim_ceiling_cents`; a larger ask is refused with `ERR_CLAIM_CEILING_EXCEEDED`. Being a fiscal rule, this is evaluated last, so a claim that is both over the ceiling and outside its window reports the window error."
    PRD: "A freshly registered host begins with `payout_hold` false and with `settled_claim_count`, `denied_claim_count` and `total_recovered_cents` all at zero, and its `version` at 1."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_precondition_beats_fiscal_ceiling_on_claim_create
    """
    cast = fixtures.setup_deposit_listing(
        api, guest_name="Omar Diaz", guest_email="omar@guest.test"
    )
    assert cast.property["claim_ceiling_cents"] == 400000, (
        "the scenario needs an ask far above this listing's ceiling"
    )
    reservation = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-12"
    )
    confirmed = fixtures.confirm_stay(api, cast, reservation["id"])
    assertions.assert_fields(confirmed, "reservation", stay_state="CONFIRMED")

    validate_error(
        api.create_damage_claim(
            cast.host_headers,
            **factories.damage_claim_payload(
                reservation["id"],
                900000,
                confirmed["version"],
                description="Water damage across two rooms.",
            )
        ),
        ApiErrorId.ERR_STAY_NOT_COMPLETED,
        expected_status=409,
    )

    assertions.assert_page(
        api.list_damage_claims(ADJUDICATOR, reservation_id=reservation["id"]),
        total_count=0,
    )
    still_confirmed = validate_success(
        api.get_reservation(reservation["id"], cast.host_headers)
    )
    assertions.assert_fields(still_confirmed, "reservation", stay_state="CONFIRMED")
    assertions.assert_version_unchanged(confirmed, still_confirmed, "reservation")
    assertions.assert_fields(
        fixtures.read_host(api, cast), "host", payout_hold=False
    )


def test_once_the_stay_is_finished_the_ceiling_answers_and_its_edge_holds(api):
    """The masked fiscal rule is real: it fires the moment the state gate passes.

    The identical 900000 ask against the identical listing now reports the ceiling
    breach with the fiscal 422, proving the earlier 409 was a matter of precedence
    rather than of the ceiling being unenforced. An ask of exactly the ceiling is
    then accepted, because the comparison forbids only exceeding it.

    PRD: "`claimed_amount_cents` must not exceed the listing's `claim_ceiling_cents`; a larger ask is refused with `ERR_CLAIM_CEILING_EXCEEDED`. Being a fiscal rule, this is evaluated last, so a claim that is both over the ceiling and outside its window reports the window error."
    PRD: "A new claim lands in `claim_state` `AWAITING_EVIDENCE` with `evidence_round` at 1 and `evidence_count` at 0."
    PRD: "Its `host_id` is *not* supplied by the client — it is copied at creation from the `host_id` of the reservation's listing."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_precondition_beats_fiscal_ceiling_on_claim_create
    """
    cast = fixtures.setup_deposit_listing(
        api, guest_name="Omar Diaz", guest_email="omar@guest.test"
    )
    completed = fixtures.complete_two_night_stay(api, cast)
    assertions.assert_fields(completed, "reservation", stay_state="COMPLETED")

    validate_error(
        api.create_damage_claim(
            cast.host_headers,
            **factories.damage_claim_payload(
                reservation_id=completed["id"],
                claimed_amount_cents=900000,
                expected_reservation_version=completed["version"],
                description="Water damage across two rooms.",
            )
        ),
        ApiErrorId.ERR_CLAIM_CEILING_EXCEEDED,
        expected_status=422,
    )
    assertions.assert_page(
        api.list_damage_claims(ADJUDICATOR, reservation_id=completed["id"]),
        total_count=0,
    )

    at_ceiling = validate_success(
        api.create_damage_claim(
            cast.host_headers,
            **factories.damage_claim_payload(
                reservation_id=completed["id"],
                claimed_amount_cents=400000,
                expected_reservation_version=completed["version"],
                description="Water damage across two rooms.",
            )
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        at_ceiling,
        "damage_claim",
        claimed_amount_cents=400000,
        claim_state="AWAITING_EVIDENCE",
        evidence_round=1,
        evidence_count=0,
        host_id=cast.host_id,
        version=1,
    )


def test_a_guests_appeal_latches_a_hold_that_blocks_the_hosts_next_filing(api):
    """The guest's own appeal, not any host action, closes the intake to the host.

    The first claim is approved in full against a waiver listing with no layers, so
    the host absorbs all of it. The guest then appeals, which latches `payout_hold`
    on the parent host — and a second, entirely unrelated claim on the same finished
    stay is refused, carrying a fresh reservation version so nothing but the hold can
    be blamed.

    PRD: "When the host's `payout_hold` flag reads true — which happens while a guest's appeal against one of that host's approved claims is pending — no further claim may be filed, and the attempt is refused with `ERR_HOST_PAYOUT_HELD`."
    PRD: "Both filing branches move `claim_state` to `APPEALED`, set `appeal_round` to 1, record `appealed_by_role`, and increase the claim's `version` by 1 — but they differ in one respect. When the guest appeals an approval, the host's `payout_hold` is set to true and the host's `version` increases by 1, which bars that host from filing any further damage claim while the appeal is pending."
    PRD: "When no layer is eligible at all, the walk's body never executes: no allocation line is written, `recovered_cents` equals the deposit slice alone, and `uncovered_cents` equals the entire post-deposit remainder."
    PRD: "Hosts can be read individually or listed with an optional `payout_hold` filter, which is how an operator finds the hosts currently barred from filing."

    Design: Difficulty/cross_entity_state_dependency/claim_intake_gated_by_host_payout_hold_from_pending_appeal
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Uma Kelly", guest_email="uma@guest.test"
    )
    reservation = fixtures.complete_three_night_stay(api, cast)
    claim = fixtures.claim_under_review(api, cast, reservation["id"], 60000)
    approved = fixtures.approve_claim(api, claim["id"], 60000)
    assertions.assert_fields(
        approved,
        "damage_claim",
        claim_state="APPROVED",
        approved_amount_cents=60000,
        recovered_cents=0,
        uncovered_cents=60000,
        host_absorbed_cents=60000,
        deposit_applied_cents=0,
    )
    host_before = fixtures.read_host(api, cast)
    assertions.assert_fields(host_before, "host", payout_hold=False)

    appealed = validate_success(
        api.appeal_damage_claim(
            claim["id"],
            cast.guest_headers,
            note="The frame was already damaged at check-in.",
        )
    )
    assertions.assert_fields(
        appealed,
        "damage_claim",
        claim_state="APPEALED",
        appeal_round=1,
        appealed_by_role="Guest",
    )
    host_after = fixtures.read_host(api, cast)
    assertions.assert_fields(host_after, "host", payout_hold=True)
    assertions.assert_version_advanced_by(host_before, host_after, 1, "host")

    current = validate_success(
        api.get_reservation(reservation["id"], cast.host_headers)
    )
    validate_error(
        api.create_damage_claim(
            cast.host_headers,
            **factories.damage_claim_payload(
                reservation_id=reservation["id"],
                claimed_amount_cents=40000,
                expected_reservation_version=current["version"],
                description="Additionally: missing patio furniture.",
            )
        ),
        ApiErrorId.ERR_HOST_PAYOUT_HELD,
        expected_status=409,
    )

    assertions.assert_page(
        api.list_damage_claims(ADJUDICATOR, reservation_id=reservation["id"]),
        total_count=1,
    )
    assertions.assert_page(
        api.list_hosts(ADJUDICATOR, payout_hold=True), total_count=1
    )


def test_a_hosts_appeal_of_a_denial_leaves_the_intake_open(api):
    """The hold is asymmetric: appealing a denial holds nothing back.

    Nothing was ever paid out on a denied claim, so the host's own appeal neither
    latches `payout_hold` nor moves the host's version, and the very same second
    filing that the guest's appeal blocked is accepted here. Both scenarios reach
    `APPEALED` with `appeal_round` 1, so the appellant is the only difference.

    PRD: "When the host appeals a denial, `payout_hold` is **not** set and the host's `version` does not move, because nothing has been paid out that would need holding. That asymmetry is deliberate."
    PRD: "The rule is symmetric: against an `APPROVED` claim the appellant must be the `Guest` of the reservation, since that guest is the charged party; against a `DENIED` claim the appellant must be the `Host` that filed it, since that host is the refused party."
    PRD: "Denial sets `decided_at`, `decided_by_user_id` and `decision_reason_code` and recomputes `appeal_due_at` identically, moves `claim_state` from `UNDER_REVIEW` to `DENIED`, and writes no money at all: `approved_amount_cents`, `recovered_cents`, `uncovered_cents` and `host_absorbed_cents` all stay at 0, no allocation line is written, no layer capacity is consumed, and the reservation's `deposit_state` is untouched."

    Design: Difficulty/cross_entity_state_dependency/claim_intake_gated_by_host_payout_hold_from_pending_appeal
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Uma Kelly", guest_email="uma@guest.test"
    )
    reservation = fixtures.complete_three_night_stay(api, cast)
    claim = fixtures.claim_under_review(api, cast, reservation["id"], 60000)
    denied = fixtures.deny_claim(api, claim["id"])
    assertions.assert_fields(
        denied,
        "damage_claim",
        claim_state="DENIED",
        approved_amount_cents=0,
        recovered_cents=0,
        uncovered_cents=0,
        host_absorbed_cents=0,
    )
    host_before = fixtures.read_host(api, cast)

    appealed = validate_success(
        api.appeal_damage_claim(
            claim["id"], cast.host_headers, note="The photographs speak for themselves."
        )
    )
    assertions.assert_fields(
        appealed,
        "damage_claim",
        claim_state="APPEALED",
        appeal_round=1,
        appealed_by_role="Host",
    )
    host_after = fixtures.read_host(api, cast)
    assertions.assert_fields(host_after, "host", payout_hold=False)
    assertions.assert_version_unchanged(host_before, host_after, "host")

    current = validate_success(
        api.get_reservation(reservation["id"], cast.host_headers)
    )
    accepted = validate_success(
        api.create_damage_claim(
            cast.host_headers,
            **factories.damage_claim_payload(
                reservation_id=reservation["id"],
                claimed_amount_cents=40000,
                expected_reservation_version=current["version"],
                description="Additionally: missing patio furniture.",
            )
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        accepted,
        "damage_claim",
        claim_state="AWAITING_EVIDENCE",
        claimed_amount_cents=40000,
        host_id=cast.host_id,
    )
    assertions.assert_page(
        api.list_damage_claims(ADJUDICATOR, reservation_id=reservation["id"]),
        total_count=2,
    )
    assertions.assert_page(
        api.list_hosts(ADJUDICATOR, payout_hold=True), total_count=0
    )
