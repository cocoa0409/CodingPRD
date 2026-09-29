"""Two-variant calculations: the preliminary vs confirmed match score on a
match candidate, and the provisional vs final reimbursement claim.

Both pairs recompute the *same* stored number from a different set of inputs, so
each test drives the pair's second variant and pins the divergence it produces.
"""
import pytest

from test_helpers import (
    assertions as A,
    factories as f,
    fixtures,
    is_iso8601_timestamp,
    validate_success,
)

# The recipient carries allele-level typing at all five loci; these two donor
# typings differ only in how much resolution the *registry* holds.
TWO_AMBIGUOUS_REGISTRY_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "08:01"],
    "C": ["07", "07"],
    "DRB1": ["15:01", "11:01"],
    "DQB1": ["06", "02"],
}

TWO_AMBIGUOUS_REPORTED_HLA = {
    "A": ["01:01", "02:01"],
    "B": ["07:02", "08:01"],
    "C": ["07:02", "07:04"],
    "DRB1": ["15:01", "11:01"],
    "DQB1": ["06:02", "02:01"],
}


def line_amounts(claim: dict) -> list:
    """The claim's seven lines as (line_type, amount_usd_cents) pairs."""
    return [(line["line_type"], line["amount_usd_cents"]) for line in claim["line_items"]]


def test_confirmed_score_diverges_from_preliminary_on_one_ambiguous_locus(api):
    """PRD §3.3: "In the preliminary variant, a locus listed in the donor's `ambiguous_loci` is compared at antigen level, meaning only the portion of each string before the colon participates; every other locus is compared at allele level, meaning the full strings must be identical."
    PRD §3.4: "When `donor_available_flag` is true, the confirmed variant of the match score is computed and stored: every one of the five loci is compared at allele level, the ambiguity penalty is zero because the reported typing carries no ambiguity, and the resulting score lands in the candidate's `confirmed_score`."
    PRD §3.4: "Because the same donor data is now compared at full resolution and without penalty, a donor with ambiguous registry loci will produce a strictly different confirmed number than its preliminary one."
    PRD §3.4: "That string is stored as the request's `reported_match_grade` and copied onto the candidate's `confirmed_match_grade`, and the candidate moves `TYPING_REQUESTED → TYPING_RESPONDED`."

    Design: Difficulty/dual_variant_calc/preliminary_vs_confirmed_match_score_diverges_on_match_candidate
    """
    ctx = fixtures.setup_pipeline("typing_requested")
    candidate = fixtures.read_candidate(ctx["candidate_id"])
    assert float(candidate["preliminary_score"]) == pytest.approx(94.75, abs=0.001), (
        "the single ambiguous locus C must be scored at antigen level and cost the "
        f"3.5-point penalty, got {candidate['preliminary_score']}"
    )

    response = api.respond_typing_request(
        ctx["typing_request_id"], f.typing_response_payload(), ctx["liaison_headers"]
    )
    typing_request = validate_success(response)
    assert typing_request["status"] == "RESPONDED"
    assert typing_request["reported_match_grade"] == "9/10"

    candidate = fixtures.read_candidate(ctx["candidate_id"])
    A.assert_match_candidate(candidate)
    assert float(candidate["preliminary_score"]) == pytest.approx(94.75, abs=0.001)
    assert float(candidate["confirmed_score"]) == pytest.approx(98.25, abs=0.001), (
        "the confirmed variant compares locus C at allele level and applies no "
        f"ambiguity penalty, got {candidate['confirmed_score']}"
    )
    divergence = float(candidate["confirmed_score"]) - float(candidate["preliminary_score"])
    assert divergence == pytest.approx(3.50, abs=0.001), (
        "the two variants must diverge by exactly the 3.5-point penalty of the one "
        f"ambiguous locus, got {divergence}"
    )
    assert candidate["confirmed_match_grade"] == "9/10"
    assert candidate["status"] == "TYPING_RESPONDED"


def test_two_ambiguous_loci_cost_seven_points_between_the_variants(api):
    """PRD §3.3: "From that base, the preliminary variant subtracts an ambiguity penalty of 3.5 points for each locus listed in `ambiguous_loci` — two ambiguous loci cost seven points, three cost ten and a half — and then adds a bonus made of three independent parts."
    PRD §3.4: "When `donor_available_flag` is true, the confirmed variant of the match score is computed and stored: every one of the five loci is compared at allele level, the ambiguity penalty is zero because the reported typing carries no ambiguity, and the resulting score lands in the candidate's `confirmed_score`."
    PRD §3.4: "Alongside the score, the response computes the allele-level matched count — the sum across the five loci of the allele-level matched counts, a whole number from 0 through 10 — and renders it as a grade string of that number followed by a slash and ten."

    Design: Difficulty/dual_variant_calc/preliminary_vs_confirmed_match_score_diverges_on_match_candidate
    """
    ctx = fixtures.setup_pipeline(
        "typing_requested",
        donor_overrides={
            "hla_typing_registry": TWO_AMBIGUOUS_REGISTRY_HLA,
            "ambiguous_loci": ["C", "DQB1"],
        },
    )
    response = api.respond_typing_request(
        ctx["typing_request_id"],
        f.typing_response_payload(reported_hla_typing=TWO_AMBIGUOUS_REPORTED_HLA),
        ctx["liaison_headers"],
    )
    validate_success(response)

    candidate = fixtures.read_candidate(ctx["candidate_id"])
    A.assert_two_decimal_places(candidate["preliminary_score"], "preliminary_score")
    A.assert_two_decimal_places(candidate["confirmed_score"], "confirmed_score")
    assert float(candidate["preliminary_score"]) == pytest.approx(82.92, abs=0.001), (
        "two ambiguous loci must cost seven points off the preliminary base, got "
        f"{candidate['preliminary_score']}"
    )
    assert float(candidate["confirmed_score"]) == pytest.approx(89.92, abs=0.001), (
        f"the confirmed variant carries no penalty, got {candidate['confirmed_score']}"
    )
    divergence = float(candidate["confirmed_score"]) - float(candidate["preliminary_score"])
    assert divergence == pytest.approx(7.00, abs=0.001), (
        f"two ambiguous loci must diverge the two variants by seven points, got {divergence}"
    )
    assert candidate["confirmed_match_grade"] == "9/10"
    assert candidate["status"] == "TYPING_RESPONDED"


def test_unavailable_donor_answer_computes_no_confirmed_score(api):
    """PRD §3.4: "When `donor_available_flag` is false instead, the registry is telling the programme the volunteer is no longer available: the request still becomes `RESPONDED`, but no confirmed score is computed at all, the donor moves `AVAILABLE → WITHDRAWN`, the candidate is moved to `EXCLUDED`, and the promotion cascade runs when that candidate was the primary."

    Design: Difficulty/dual_variant_calc/preliminary_vs_confirmed_match_score_diverges_on_match_candidate
    """
    ctx = fixtures.setup_pipeline("typing_requested")

    response = api.respond_typing_request(
        ctx["typing_request_id"],
        f.typing_response_payload(donor_available_flag=False),
        ctx["liaison_headers"],
    )
    typing_request = validate_success(response)
    assert typing_request["status"] == "RESPONDED"

    candidate = fixtures.read_candidate(ctx["candidate_id"])
    assert candidate["confirmed_score"] is None, (
        "an unavailable answer computes no confirmed score at all, got "
        f"{candidate['confirmed_score']!r}"
    )
    assert float(candidate["preliminary_score"]) == pytest.approx(94.75, abs=0.001), (
        "the preliminary variant's stored value is untouched by the response"
    )
    assert candidate["status"] == "EXCLUDED"
    assert fixtures.read_donor(ctx["donor_id"])["availability_status"] == "WITHDRAWN"


def test_final_claim_reprices_collection_and_lost_wage_from_the_authorised_method(
    api, operations_headers
):
    """PRD §3.9: "The **provisional** variant runs at claim creation, before any collection method has been decided, so it cannot know the real method: it assumes `PBSC` for the collection line and the cancellation line's basis, assumes a window-day count of 6 for the lost-wage line, always charges a zero cancellation line, and captures `fx_rate_snapshot` from the registry as read at creation."
    PRD §3.9: "The **final** variant runs at finalisation: it uses the case's actual `collection_method` for the collection line, the case's actual `planned_window_days` for the lost-wage line, charges the cancellation line when a confirmed booking of the case was cancelled, and re-reads `fx_rate_snapshot` from the registry at that moment."
    PRD §3.9: "A successful finalisation moves the claim `PROVISIONAL → FINALIZED`, sets `variant_applied` to `FINAL`, recomputes every line, the discount tier, the coordination fee, the total and the local billed amount against the freshly read rate, and stamps `finalized_at` from the logical clock."
    PRD §3.9: "The patient's `committed_cost_cents` then moves by the difference between the final total and the provisional total it previously carried — upward when the final numbers are larger, downward when they are smaller — because both `PROVISIONAL` and `FINALIZED` claims count towards that commitment."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_reimbursement_claim_diverges_on_claim
    """
    ctx = fixtures.setup_pipeline("delivered", method="MARROW")

    provisional = fixtures.read_claim(ctx["claim_id"])
    assert provisional["variant_applied"] == "PROVISIONAL"
    assert A.claim_line(provisional, "COLLECTION") == 1450000, (
        "the provisional variant assumes PBSC for the collection line"
    )
    assert A.claim_line(provisional, "DONOR_LOST_WAGE") == 192000, (
        "the provisional variant assumes a window-day count of 6"
    )
    assert A.claim_line(provisional, "CANCELLATION") == 0
    assert provisional["total_usd_cents"] == 2072000
    assert float(provisional["volume_discount_pct"]) == 0.0, (
        "a 2072000-cent subtotal sits below the 2500000-cent tier"
    )
    assert fixtures.read_patient(ctx["patient_id"])["committed_cost_cents"] == 2072000

    fixtures.drive_conditioning(ctx, "INFUSE")

    claim = validate_success(
        api.finalize_reimbursement_claim(ctx["claim_id"], operations_headers)
    )
    A.assert_reimbursement_claim(claim)
    A.assert_claim_arithmetic(claim)
    assert claim["status"] == "FINALIZED"
    assert claim["variant_applied"] == "FINAL"
    assert is_iso8601_timestamp(claim["finalized_at"])
    assert line_amounts(claim) == [
        ("CT_TYPING", 34500),
        ("WORKUP_PHYSICAL", 78000),
        ("IDM_PANEL", 52500),
        ("COLLECTION", 1980000),
        ("COURIER", 265000),
        ("DONOR_LOST_WAGE", 256000),
        ("CANCELLATION", 0),
    ], f"the final variant must reprice from MARROW and 8 window days, got {line_amounts(claim)}"
    assert claim["subtotal_usd_cents"] == 2666000
    assert float(claim["volume_discount_pct"]) == 0.05, (
        "the repriced 2666000-cent subtotal crosses the 2500000-cent discount tier"
    )
    assert claim["discount_usd_cents"] == 133300
    assert claim["intl_coordination_fee_usd_cents"] == 0
    assert claim["total_usd_cents"] == 2532700
    assert claim["billed_amount_local_cents"] == 2532700
    assert fixtures.read_patient(ctx["patient_id"])["committed_cost_cents"] == 2532700, (
        "committed_cost_cents must move by 2532700 - 2072000 to the final total"
    )


def test_only_the_final_variant_picks_up_a_changed_registry_fx_rate(
    api, operations_headers
):
    """PRD §3.1: "A new `fx_rate_to_usd` affects only claim numbers computed after the change: a claim already sitting in `PROVISIONAL` keeps the `fx_rate_snapshot` it captured, and only picks up the new rate if and when it is finalised."
    PRD §3.9: "Because the rate is re-read, a registry whose `fx_rate_to_usd` changed in between will yield a different `billed_amount_local_cents` for an identical United States dollar total."
    PRD §3.9: "Finally, `billed_amount_local_cents` converts that total into the registry's own currency: the total divided by `fx_rate_snapshot`, rounded half up to a whole local cent."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_reimbursement_claim_diverges_on_claim
    """
    ctx = fixtures.setup_pipeline("delivered", method="PBSC")

    provisional = fixtures.read_claim(ctx["claim_id"])
    assert provisional["variant_applied"] == "PROVISIONAL"
    assert float(provisional["fx_rate_snapshot"]) == pytest.approx(1.0000, abs=0.00001)
    assert provisional["total_usd_cents"] == 2072000
    assert provisional["billed_amount_local_cents"] == 2072000

    validate_success(
        api.update_registry(
            ctx["registry_id"], {"fx_rate_to_usd": 1.2500}, operations_headers
        )
    )

    still_provisional = fixtures.read_claim(ctx["claim_id"])
    assert float(still_provisional["fx_rate_snapshot"]) == pytest.approx(
        1.0000, abs=0.00001
    ), "a claim sitting in PROVISIONAL keeps the snapshot it captured at creation"
    assert still_provisional["billed_amount_local_cents"] == 2072000

    fixtures.drive_conditioning(ctx, "INFUSE")

    claim = validate_success(
        api.finalize_reimbursement_claim(ctx["claim_id"], operations_headers)
    )
    assert claim["variant_applied"] == "FINAL"
    assert float(claim["fx_rate_snapshot"]) == pytest.approx(1.2500, abs=0.00001), (
        "finalisation re-reads fx_rate_to_usd from the registry at that moment, got "
        f"{claim['fx_rate_snapshot']}"
    )
    assert claim["total_usd_cents"] == 2072000, (
        "the PBSC method and 6 window days make the final lines identical to the "
        "provisional ones, so the dollar total must not move"
    )
    assert claim["billed_amount_local_cents"] == 1657600, (
        "2072000 divided by the freshly read 1.2500 rate, got "
        f"{claim['billed_amount_local_cents']}"
    )


def test_cancellation_line_is_charged_by_the_final_variant_alone(
    api, operations_headers
):
    """PRD §3.9: "The `CANCELLATION` line is the collection fee for the variant's method multiplied by 0.40, that is forty per cent, rounded half up to whole cents, and it is charged only in the final variant and only when some booking of the case carries `cancelled_after_confirmation` true; in every other situation it is zero."
    PRD §3.9: "When that line is charged, the claim's `cancellation_fee_applied` is recorded as true."
    PRD §3.9: "From the subtotal alone — never from the total, never from any individual line — a `volume_discount_pct` is selected: a subtotal of at least 4,000,000 cents earns 0.09, otherwise a subtotal of at least 2,500,000 cents earns 0.05, and anything below that earns nothing."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_reimbursement_claim_diverges_on_claim
    """
    ctx = fixtures.setup_pipeline("booking_confirmed", method="PBSC")

    booking = fixtures.cancel_booking(ctx, reason="Donor developed a febrile illness")
    assert booking["status"] == "CANCELLED"
    assert booking["cancelled_after_confirmation"] is True

    provisional = fixtures.read_claim(ctx["claim_id"])
    assert provisional["variant_applied"] == "PROVISIONAL"
    assert A.claim_line(provisional, "CANCELLATION") == 0, (
        "the provisional variant always charges a zero cancellation line, even once "
        "a confirmed booking has been cancelled"
    )
    assert provisional["cancellation_fee_applied"] is False
    assert provisional["total_usd_cents"] == 2072000

    claim = validate_success(
        api.finalize_reimbursement_claim(ctx["claim_id"], operations_headers)
    )
    A.assert_claim_arithmetic(claim)
    assert claim["variant_applied"] == "FINAL"
    assert A.claim_line(claim, "CANCELLATION") == 580000, (
        "forty per cent of the PBSC collection fee of 1450000, got "
        f"{A.claim_line(claim, 'CANCELLATION')}"
    )
    assert claim["cancellation_fee_applied"] is True
    assert A.claim_line(claim, "COLLECTION") == 1450000
    assert A.claim_line(claim, "DONOR_LOST_WAGE") == 192000
    assert claim["subtotal_usd_cents"] == 2652000
    assert float(claim["volume_discount_pct"]) == 0.05, (
        "the cancellation line pushes the subtotal across the 2500000-cent tier"
    )
    assert claim["discount_usd_cents"] == 132600
    assert claim["intl_coordination_fee_usd_cents"] == 0
    assert claim["total_usd_cents"] == 2519400
    assert fixtures.read_patient(ctx["patient_id"])["committed_cost_cents"] == 2519400
