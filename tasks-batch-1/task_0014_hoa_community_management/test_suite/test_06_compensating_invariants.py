"""Compensating-action invariants (PRD §3.2 payment reverse; §3.7 vote
retract)."""
from test_helpers import (
    bootstrap_election_open_with_voters,
    bootstrap_tenant,
    cast_vote,
    create_assessment,
    get_election,
    get_property,
    validate_success,
)
from test_helpers.test_users import (
    make_homeowner_headers,
    make_treasurer_headers,
)


# ─────────────────────────────────────────────────────────────────────────────
# Rule 9 instance 1: payment reverse preserves Property.account_balance_cents
# ─────────────────────────────────────────────────────────────────────────────

def test_payment_reverse_restores_property_account_balance(api):
    """PRD §3.2: "A treasurer can also reverse a previously applied
    `PaymentApplication` as a compensating action. Reversing flips its
    `state` to `REVERSED`, recomputes `paid_cents` and `outstanding_cents`
    on the underlying assessment by re-summing the property's remaining
    `APPLIED` rows, and refreshes the property's `account_balance_cents`.
    The invariant the reversal preserves is that the property's
    `account_balance_cents` returns to its pre-payment value."

    Setup: principal 10000 → balance 10000. Pay 4000 → balance 6000.
    Reverse the payment → balance must return to 10000 exactly.

    Design: Difficulty/compensating_invariant/payment_reverse_preserves_property_account_balance
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Inv1", owner_email="inv1@x.com", owner_name="INV1",
        unit_label="INV1-1", regular_assessment_cents=10000,
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=10000,
        due_date="2026-06-01T00:00:00Z",
    )
    bal_before = get_property(prop["id"])["account_balance_cents"]
    assert bal_before == 10000, f"pre-payment balance must be 10000, got {bal_before}"
    pay_resp = api.create_payment(
        {
            "assessment_id": a["id"],
            "amount_cents": 4000,
            "expected_assessment_version": a["version"],
        },
        make_treasurer_headers(),
    )
    pa = validate_success(pay_resp, expected_status=201)
    bal_mid = get_property(prop["id"])["account_balance_cents"]
    assert bal_mid == 6000, f"mid-payment balance must be 6000, got {bal_mid}"
    reversed_resp = api.reverse_payment(pa["id"], make_treasurer_headers())
    rev_data = validate_success(reversed_resp, expected_status=200)
    assert rev_data["state"] == "REVERSED", (
        f"reversed payment state must be REVERSED, got {rev_data['state']}"
    )
    bal_after = get_property(prop["id"])["account_balance_cents"]
    assert bal_after == bal_before, (
        f"reversal invariant: balance_after_reverse ({bal_after}) must equal "
        f"balance_before_payment ({bal_before})"
    )


def test_payment_reverse_recomputes_assessment_outstanding(api):
    """PRD §3.2: "Reversing flips its `state` to `REVERSED`, recomputes
    `paid_cents` and `outstanding_cents` on the underlying assessment by
    re-summing the property's remaining `APPLIED` rows, and refreshes the
    property's `account_balance_cents`."

    Setup: pay partial 4000 against principal 10000 → paid=4000,
    outstanding=6000. Reverse → paid recomputes to 0 (no remaining APPLIED
    rows), outstanding back to 10000.

    Design: Difficulty/compensating_invariant/payment_reverse_preserves_property_account_balance
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Inv1Out", owner_email="inv1o@x.com", owner_name="INV1O",
        unit_label="INV1-O", regular_assessment_cents=10000,
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=10000,
        due_date="2026-06-01T00:00:00Z",
    )
    pay_resp = api.create_payment(
        {
            "assessment_id": a["id"],
            "amount_cents": 4000,
            "expected_assessment_version": a["version"],
        },
        make_treasurer_headers(),
    )
    pa = validate_success(pay_resp, expected_status=201)
    a_mid = validate_success(
        api.get_assessment(a["id"], make_treasurer_headers()),
        expected_status=200,
    )
    assert a_mid["paid_cents"] == 4000
    assert a_mid["outstanding_cents"] == 6000
    validate_success(
        api.reverse_payment(pa["id"], make_treasurer_headers()),
        expected_status=200,
    )
    a_after = validate_success(
        api.get_assessment(a["id"], make_treasurer_headers()),
        expected_status=200,
    )
    assert a_after["paid_cents"] == 0, (
        f"paid_cents must be recomputed by re-summing APPLIED rows, "
        f"got {a_after['paid_cents']}"
    )
    assert a_after["outstanding_cents"] == 10000, (
        f"outstanding_cents must reflect 0 paid, got {a_after['outstanding_cents']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule 9 instance 2: vote retract preserves votes_cast invariant
# ─────────────────────────────────────────────────────────────────────────────

def test_vote_retract_decrements_votes_cast_back_to_pre_cast_value(api):
    """PRD §3.7: "An owner who wishes to change their mind may retract a
    `CAST` vote while the election remains `OPEN`, moving its `state` to
    `RETRACTED`; a `RETRACTED` vote does NOT block the same owner from
    subsequently casting a fresh `CAST` vote (so the uniqueness rule is
    properly stated as one CAST vote per pairing, not one row per pairing).
    Both casting and retracting recompute `votes_cast` on the election,
    which is the count of the election's `Vote` rows whose `state` is
    `CAST`."

    Setup: Election OPEN with one Owner. votes_cast starts at 0. Cast →
    votes_cast=1. Retract → state=RETRACTED and votes_cast back to 0
    (compensating invariant).

    Design: Difficulty/compensating_invariant/vote_retract_preserves_votes_cast_invariant
    """
    _community, owners, election = bootstrap_election_open_with_voters(
        community_name="Inv2",
        eligible_owner_count=1,
        cycle_label="INV2-FY",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
        clock_before_open="2026-01-15T00:00:00Z",
        clock_after_open="2026-02-02T00:00:00Z",
    )
    owner = owners[0]
    e_pre = get_election(election["id"])
    assert e_pre["votes_cast"] == 0
    vote = cast_vote(election["id"], owner["id"], candidate_name="Alice")
    e_mid = get_election(election["id"], as_owner_id=owner["id"])
    assert e_mid["votes_cast"] == 1
    retracted_resp = api.retract_vote(
        vote["id"], make_homeowner_headers(owner["id"]),
    )
    retracted = validate_success(retracted_resp, expected_status=200)
    assert retracted["state"] == "RETRACTED", (
        f"retracted vote state must be RETRACTED, got {retracted['state']}"
    )
    e_post = get_election(election["id"], as_owner_id=owner["id"])
    assert e_post["votes_cast"] == 0, (
        f"votes_cast must return to pre-cast value 0 after retract, "
        f"got {e_post['votes_cast']}"
    )


def test_retracted_vote_does_not_block_owner_casting_fresh_vote(api):
    """PRD §3.7: "An owner who wishes to change their mind may retract a
    `CAST` vote while the election remains `OPEN`, moving its `state` to
    `RETRACTED`; a `RETRACTED` vote does NOT block the same owner from
    subsequently casting a fresh `CAST` vote (so the uniqueness rule is
    properly stated as one CAST vote per pairing, not one row per pairing)."

    Compensation companion: after a retract, the same owner can cast a
    fresh vote — the retracted row is inert, not a blocker. This also
    proves the votes_cast counter re-increments to 1 on the new cast.

    Design: Difficulty/compensating_invariant/vote_retract_preserves_votes_cast_invariant
    """
    _community, owners, election = bootstrap_election_open_with_voters(
        community_name="Inv2Cont",
        eligible_owner_count=1,
        cycle_label="INV2C-FY",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
        clock_before_open="2026-01-15T00:00:00Z",
        clock_after_open="2026-02-02T00:00:00Z",
    )
    owner = owners[0]
    v1 = cast_vote(election["id"], owner["id"], candidate_name="Alice")
    validate_success(
        api.retract_vote(v1["id"], make_homeowner_headers(owner["id"])),
        expected_status=200,
    )
    # Same owner casts a NEW vote — must succeed.
    resp = api.create_vote(
        {
            "election_id": election["id"],
            "owner_id": owner["id"],
            "candidate_name": "Bob",
        },
        make_homeowner_headers(owner["id"]),
    )
    v2 = validate_success(resp, expected_status=201)
    assert v2["state"] == "CAST"
    e_after = get_election(election["id"], as_owner_id=owner["id"])
    assert e_after["votes_cast"] == 1, (
        f"votes_cast must be 1 after retract+new-cast, got {e_after['votes_cast']}"
    )
