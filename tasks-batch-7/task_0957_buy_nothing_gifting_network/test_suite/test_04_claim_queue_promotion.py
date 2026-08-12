"""Claim queue promotion policies: FIRST_COME chronology, FAIRNESS_DRAW score
ordering, GIVER_PICK explicit selection, and the strict offer deadline
(PRD §2.8, §2.10, §2.11, §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_iso_instant,
    create_and_publish_post,
    create_claim,
    get_claim,
    get_post,
    make_member_headers,
    set_clock,
    setup_group_with_members,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# GIVER_PICK selector policy (Corner/complexity_layers)
# ---------------------------------------------------------------------------

def _setup_giver_pick_queue():
    group, members = setup_group_with_members(
        [("gpg@x.com", "G"), ("gpc1@x.com", "C1"), ("gpc2@x.com", "C2")],
        name="Pick Group", zip_code="98240",
    )
    g, c1, c2 = members["gpg@x.com"], members["gpc1@x.com"], members["gpc2@x.com"]
    post = create_and_publish_post(g, group, title="Piano", claim_mode="GIVER_PICK")
    cl1 = create_claim(c1, post)
    cl2 = create_claim(c2, post)
    return group, g, c1, c2, post, cl1, cl2


def test_giver_pick_no_auto_promotion_and_explicit_selection(api):
    """PRD §3.3: "Under `GIVER_PICK` there is no automatic promotion at all: the
    giver explicitly selects any `QUEUED` claim of the post, and attempting to
    offer a claim that is not `QUEUED` on that post fails with
    `ERR_CLAIM_NOT_QUEUED`."

    Design: Corner/complexity_layers/selector_giver_pick_explicit_offer
    """
    group, g, c1, c2, post, cl1, cl2 = _setup_giver_pick_queue()
    assert cl1["status"] == "QUEUED", (
        "no auto-promotion under GIVER_PICK even with a vacant head slot"
    )
    assert cl2["status"] == "QUEUED"

    # The giver selects the SECOND claim — not the chronological first.
    res = api.offer_gift_post(post["id"], {"claim_id": cl2["id"]}, make_member_headers(g["id"]))
    offered = validate_success(res, 200)
    assert offered["status"] == "OFFERED"
    assert_iso_instant(offered["offer_expires_at"], "2026-05-11T09:00:00Z")

    cl1_after = get_claim(cl1["id"], make_member_headers(c1["id"]))
    assert cl1_after["status"] == "QUEUED", "the unselected claim stays QUEUED"
    post_after = get_post(post["id"], make_member_headers(g["id"]))
    assert post_after["status"] == "RESERVED"
    assert post_after["current_claim_id"] == cl2["id"]


def test_offer_to_foreign_claim_rejected(api):
    """PRD §3.3: "Under `GIVER_PICK` there is no automatic promotion at all: the
    giver explicitly selects any `QUEUED` claim of the post, and attempting to
    offer a claim that is not `QUEUED` on that post fails with
    `ERR_CLAIM_NOT_QUEUED`."

    Design: Corner/complexity_layers/offer_to_foreign_claim_rejected
    """
    group, members = setup_group_with_members(
        [("ofg@x.com", "G"), ("ofc@x.com", "C")],
        name="Foreign Offer Group", zip_code="98241",
    )
    g, c = members["ofg@x.com"], members["ofc@x.com"]
    p1 = create_and_publish_post(g, group, title="Chair P1", category="FURNITURE",
                                 claim_mode="GIVER_PICK")
    p2 = create_and_publish_post(g, group, title="Chair P2", category="FURNITURE",
                                 claim_mode="GIVER_PICK")
    cl_c = create_claim(c, p2)
    assert cl_c["status"] == "QUEUED"

    res = api.offer_gift_post(p1["id"], {"claim_id": cl_c["id"]}, make_member_headers(g["id"]))
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_QUEUED, expected_status=409)
    post_after = get_post(p1["id"], make_member_headers(g["id"]))
    assert post_after["status"] == "OPEN"
    assert post_after["current_claim_id"] is None


# ---------------------------------------------------------------------------
# Offer-accept deadline boundary (Difficulty/boundary_precision_check)
# ---------------------------------------------------------------------------

def _setup_two_live_offers():
    """Two posts, one OFFERED claim each; both offers expire 2026-05-11T09:00:00Z."""
    group, members = setup_group_with_members(
        [("og@x.com", "G"), ("om1@x.com", "M1"), ("om2@x.com", "M2")],
        name="Offer Group", zip_code="98111",
    )
    g, m1, m2 = members["og@x.com"], members["om1@x.com"], members["om2@x.com"]
    p1 = create_and_publish_post(g, group, title="Blender", category="HOUSEHOLD")
    c1 = create_claim(m1, p1)
    p2 = create_and_publish_post(g, group, title="Mixer", category="HOUSEHOLD")
    c2 = create_claim(m2, p2)
    assert c1["status"] == "OFFERED" and c2["status"] == "OFFERED"
    return group, g, m1, m2, p1, p2, c1, c2


def test_offer_accept_one_second_before_deadline_succeeds(api):
    """PRD §2.11: "Offer windows use a strict deadline: an offer is acceptable
    only while the logical now is strictly before the claim's
    `offer_expires_at`; at the exact instant of `offer_expires_at` the offer is
    already expired."
    PRD §3.3: "The offered claimer may then accept — but only while the logical
    now is strictly before `offer_expires_at`, only on a claim still `OFFERED`
    (`ERR_CLAIM_NOT_OFFERED` otherwise, which also greets acceptances attempted
    after the sweep has already expired the offer), and only as themselves
    (`ERR_NOT_RESOURCE_OWNER`)."

    Design: Difficulty/boundary_precision_check/offer_accept_deadline_exact_equality
    """
    group, g, m1, m2, p1, p2, c1, c2 = _setup_two_live_offers()
    set_clock("2026-05-11T08:59:59Z")  # one second before the deadline
    res = api.accept_claim(c1["id"], make_member_headers(m1["id"]))
    accepted = validate_success(res, 200)
    assert accepted["status"] == "ACCEPTED", (
        "accept at now == offer_expires_at - 1s must succeed (strict < deadline)"
    )


def test_offer_accept_at_exact_deadline_rejected_and_swept(api):
    """PRD §2.11: "Offer windows use a strict deadline: an offer is acceptable
    only while the logical now is strictly before the claim's
    `offer_expires_at`; at the exact instant of `offer_expires_at` the offer is
    already expired."
    PRD §3.3: "At the boundary instant itself the offer is already gone: when
    the clock reaches `offer_expires_at` the sweep moves the claim from
    `OFFERED` to `EXPIRED`."

    Design: Difficulty/boundary_precision_check/offer_accept_deadline_exact_equality
    """
    group, g, m1, m2, p1, p2, c1, c2 = _setup_two_live_offers()
    set_clock("2026-05-11T09:00:00Z")  # exact equality with offer_expires_at
    res = api.accept_claim(c2["id"], make_member_headers(m2["id"]))
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_OFFERED, expected_status=409)
    claim_after = get_claim(c2["id"], make_member_headers(m2["id"]))
    assert claim_after["status"] == "EXPIRED", "the sweep fires at exact equality"
    post_after = get_post(p2["id"], make_member_headers(g["id"]))
    assert post_after["status"] == "OPEN", "queue empty -> post falls back to OPEN"
    assert post_after["current_claim_id"] is None
    assert post_after["current_offer_expires_at"] is None
