"""DNA-relative matching, the suppression/re-grant cascades, and the family-tree surface."""

import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    CLOCK_START,
    validate_success,
    validate_error,
    validate_paginated,
    assert_relative_match,
    assert_record_hint,
    assert_q2_conserved,
    make_customer_headers,
    make_platform_admin_headers,
    factories as f,
    fixtures as fx,
)

ADMIN = make_platform_admin_headers()


# ═══════════════════════════════════════════════════════════════════════════
# The 8.00 cM inclusive boundary
# ═══════════════════════════════════════════════════════════════════════════

def _setup_boundary_trio():
    """A and B share markers {1, 2} → 8.00 cM (exactly the threshold).
    C shares only {1} with either → 4.00 cM (below it)."""
    fx.set_clock(CLOCK_START)
    a, b, c = fx.setup_dna_ready_group(
        [
            {"email": "bnd-a@dna.test", "display_name": "BndA", "genotype_markers": [1, 2]},
            {"email": "bnd-b@dna.test", "display_name": "BndB", "genotype_markers": [1, 2]},
            {"email": "bnd-c@dna.test", "display_name": "BndC", "genotype_markers": [1, 7]},
        ]
    )
    for p in (a, b, c):
        fx.grant_consent(p["customer"]["id"], "RELATIVE_MATCHING")
    return a, b, c


def test_exactly_eight_centimorgans_creates_a_match(api):
    """PRD §3.8: "A relative match is created if and only if `shared_cm` is **at least 8.00**
    — the boundary is inclusive, so exactly 8.00 does create a match while 4.00 does not."
    PRD §3.8: "The shared centimorgan figure, `shared_cm`, is 4.00 centimorgans per shared
    marker, multiplied by the number of shared markers, rounded half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/match_min_cm_inclusive_at_exactly_eight_centimorgans
    """
    a, _b, _c = _setup_boundary_trio()

    matches = validate_success(
        api.recompute_matches(a["customer"]["id"], make_customer_headers(a["customer"]["id"]))
    )
    assert len(matches) == 1, f"Expected exactly 1 match at the 8.00 cM boundary, got {len(matches)}"

    match = matches[0]
    assert_relative_match(match)
    assert match["shared_cm"] == pytest.approx(8.0, abs=0.001)
    assert match["segment_count"] == 1, "Markers 1 and 2 form a single consecutive run"
    assert match["predicted_relationship"] == "DISTANT_COUSIN"
    # 0.70 * min(1, 8/400) + 0.30 * min(1, 1/4) - 0.0 == 0.014 + 0.075 == 0.0890
    assert match["confidence_score"] == pytest.approx(0.089, abs=0.0001)


def test_four_centimorgans_creates_no_match(api):
    """PRD §3.8: "A relative match is created if and only if `shared_cm` is **at least 8.00**
    — the boundary is inclusive, so exactly 8.00 does create a match while 4.00 does not."
    PRD §3.8: "Both customers' `visible_match_count` is incremented by one — the count is, at
    all times, the number of matches in `ACTIVE` status naming that customer on either side
    of the pair, and it never goes below zero."

    Design: Difficulty/boundary_precision_check/match_min_cm_inclusive_at_exactly_eight_centimorgans
    """
    a, b, c = _setup_boundary_trio()

    fx.recompute_matches(a["customer"]["id"])

    below = validate_success(
        api.recompute_matches(c["customer"]["id"], make_customer_headers(c["customer"]["id"]))
    )
    assert below == [], (
        "A single shared marker is 4.00 cM, below the 8.00 threshold — nothing may be created"
    )

    assert fx.read_customer(c["customer"]["id"])["visible_match_count"] == 0
    assert fx.read_customer(a["customer"]["id"])["visible_match_count"] == 1
    assert fx.read_customer(b["customer"]["id"])["visible_match_count"] == 1


def test_chip_mismatch_penalty_lowers_the_confidence_score(api):
    """PRD §3.8: "The third is a chip penalty: if the `chip_version` of the kit behind side
    A's source sample differs from the `chip_version` of the kit behind side B's source
    sample, a penalty of 0.05 applies; if the chips agree, the penalty is zero."
    PRD §3.8: "`customer_a_id` is the side of the pair whose customer record has the earlier
    `created_at`; if the two were created at the same instant, it is the side with the
    lexicographically lower `email`."

    Design: Corner/calculations/relative_match_chip_mismatch_penalty_lowers_confidence
    """
    fx.set_clock(CLOCK_START)
    v4, v5 = fx.setup_dna_ready_group(
        [
            {
                "email": "v4@dna.test",
                "display_name": "V4C",
                "chip_version": "V4",
                "genotype_markers": [1, 2],
            },
            {
                "email": "v5@dna.test",
                "display_name": "V5C",
                "chip_version": "V5",
                "genotype_markers": [1, 2],
            },
        ]
    )
    fx.grant_consent(v4["customer"]["id"], "RELATIVE_MATCHING")
    fx.grant_consent(v5["customer"]["id"], "RELATIVE_MATCHING")

    matches = validate_success(
        api.recompute_matches(
            v4["customer"]["id"], make_customer_headers(v4["customer"]["id"])
        )
    )
    assert len(matches) == 1
    match = matches[0]

    # Same 8.00 cM / 1 segment as the same-chip pair, but 0.0890 - 0.05 == 0.0390.
    assert match["confidence_score"] == pytest.approx(0.039, abs=0.0001), (
        f"Expected the chip-mismatch penalty to drop confidence to 0.039, "
        f"got {match['confidence_score']}"
    )
    assert match["shared_cm"] == pytest.approx(8.0, abs=0.001)
    assert match["segment_count"] == 1
    assert match["customer_a_id"] == v4["customer"]["id"]
    assert match["customer_b_id"] == v5["customer"]["id"]


# ═══════════════════════════════════════════════════════════════════════════
# The four-hop consent-withdrawal cascade
# ═══════════════════════════════════════════════════════════════════════════

def test_withdrawing_matching_consent_flips_the_flag_and_suppresses_the_match(api):
    """PRD §3.6: "- **`RELATIVE_MATCHING`**: the four-hop suppression cascade fires,
    described in Section 3.7."
    PRD §3.8: "When one side's `matching_opt_in` becomes false, every `ACTIVE` match
    involving that customer transitions `ACTIVE → SUPPRESSED`."

    Design: Difficulty/transitive_cascade/consent_withdraw_relative_matching_four_hop_cascade
    """
    setup = fx.setup_matched_pair_with_trees()
    a_id = setup["a"]["customer"]["id"]
    grant_a = setup["grant_a"]
    match_id = setup["match"]["id"]

    withdrawn = validate_success(
        api.withdraw_consent_grant(grant_a["id"], make_customer_headers(a_id))
    )
    assert withdrawn["status"] == "WITHDRAWN"

    # hop 1: the flag. hop 2: the match — caused by the flag, not by the withdraw call.
    assert fx.read_customer(a_id)["matching_opt_in"] is False
    assert fx.read_match(match_id, a_id)["status"] == "SUPPRESSED"


def test_suppression_decrements_both_counts_and_withdraws_the_planted_hints(api):
    """PRD §3.8: "Because the match left `ACTIVE`, both sides' `visible_match_count` is
    decremented by one — the counterpart, who consented to nothing and did nothing, sees
    their relative count drop. And because the match left `ACTIVE`, every `PENDING` record
    hint whose `source_match_id` names that match transitions `PENDING → WITHDRAWN`, and the
    `hint_count` of the tree person each such hint hung from is decremented by one."

    Design: Difficulty/transitive_cascade/consent_withdraw_relative_matching_four_hop_cascade
    """
    setup = fx.setup_matched_pair_with_trees()
    a_id = setup["a"]["customer"]["id"]
    b_id = setup["b"]["customer"]["id"]
    match_id = setup["match"]["id"]
    person_a = setup["person_a"]
    person_b = setup["person_b"]

    # Precondition: one hint on each side's root person.
    assert fx.read_person(person_a["id"], a_id)["hint_count"] == 1
    assert fx.read_person(person_b["id"], b_id)["hint_count"] == 1

    validate_success(
        api.withdraw_consent_grant(setup["grant_a"]["id"], make_customer_headers(a_id))
    )

    # hop 3: both counters, including the counterpart who did nothing.
    assert fx.read_customer(a_id)["visible_match_count"] == 0
    assert fx.read_customer(b_id)["visible_match_count"] == 0

    # hop 4: the hints and the tree people they hung from. The two hints sit on two different
    # customers' trees, so this listing is made with the operator role that reads across both.
    hints, meta = validate_paginated(
        api.list_record_hints(ADMIN, params={"source_match_id": match_id})
    )
    assert meta["total_count"] == 2, f"Expected 2 hints from the match, got {meta['total_count']}"
    for hint in hints:
        assert_record_hint(hint)
        assert hint["status"] == "WITHDRAWN"

    assert fx.read_person(person_a["id"], a_id)["hint_count"] == 0
    assert fx.read_person(person_b["id"], b_id)["hint_count"] == 0

    # B's own consent was never touched.
    assert fx.read_customer(b_id)["matching_opt_in"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Q2: visible_match_count conserved across withdrawal and re-grant
# ═══════════════════════════════════════════════════════════════════════════

def _withdraw_and_regrant_pair():
    """Matched pair, then a withdrawal at 2026-05-02 and a re-grant at exactly +24h."""
    fx.set_clock(CLOCK_START)
    setup = fx.setup_matched_pair(email_a="x@dna.test", email_b="y@dna.test")
    assert len(setup["matches"]) == 1, "Setup failed: expected exactly one match"
    setup["match"] = setup["matches"][0]

    fx.set_clock("2026-05-02T00:00:00Z")
    fx.withdraw_consent(setup["grant_a"]["id"], setup["a"]["customer"]["id"])
    fx.set_clock("2026-05-03T00:00:00Z")
    return setup


def test_q2_holds_at_zero_after_withdrawal_and_returns_to_two_after_the_regrant(api):
    """PRD §2.10: "The second: summing `visible_match_count` over every customer always
    yields exactly twice the number of relative matches currently in `ACTIVE` status, because
    every active match contributes to precisely two customers' counts. This must hold after a
    consent withdrawal, after a re-grant, and after a purge."

    Design: Difficulty/compensating_invariant/q2_counter_visible_match_count_conserved_under_withdraw_and_regrant
    """
    setup = _withdraw_and_regrant_pair()
    a_id = setup["a"]["customer"]["id"]
    b_id = setup["b"]["customer"]["id"]
    match_id = setup["match"]["id"]

    # After the withdrawal: 0 ACTIVE matches, so the counters must sum to 0.
    assert fx.read_match(match_id, b_id)["status"] == "SUPPRESSED"
    assert_q2_conserved([fx.read_customer(a_id), fx.read_customer(b_id)], 0)

    regrant = validate_success(
        api.create_consent_grant(
            f.create_consent_payload(
                a_id,
                "RELATIVE_MATCHING",
                effective_from="2026-05-03T00:00:00Z",
                effective_until="2026-12-31T00:00:00Z",
            ),
            make_customer_headers(a_id),
        ),
        201,
    )
    assert regrant["status"] == "ACTIVE"

    # After the re-grant: 1 ACTIVE match again, so the counters must sum back to 2.
    assert fx.read_match(match_id, a_id)["status"] == "ACTIVE"
    assert_q2_conserved([fx.read_customer(a_id), fx.read_customer(b_id)], 1)


def test_the_regrant_reactivates_the_existing_match_without_duplicating_it(api):
    """PRD §3.6: "Second, every relative match involving that customer that currently sits in
    `SUPPRESSED` status, and whose *other* side also has `matching_opt_in` true, transitions
    `SUPPRESSED → ACTIVE`."
    PRD §3.6: "Third, because those matches became active again, both customers on each
    reactivated pair have their `visible_match_count` incremented by one, restoring the
    doubling invariant of Section 2.10."

    Design: Difficulty/compensating_invariant/q2_counter_visible_match_count_conserved_under_withdraw_and_regrant
    """
    setup = _withdraw_and_regrant_pair()
    a_id = setup["a"]["customer"]["id"]
    b_id = setup["b"]["customer"]["id"]
    headers_a = make_customer_headers(a_id)

    # Exactly 24 hours after withdrawn_at — the inclusive edge of the cooling-off buffer.
    validate_success(
        api.create_consent_grant(
            f.create_consent_payload(
                a_id,
                "RELATIVE_MATCHING",
                effective_from="2026-05-03T00:00:00Z",
                effective_until="2026-12-31T00:00:00Z",
            ),
            headers_a,
        ),
        201,
    )

    assert fx.read_customer(a_id)["visible_match_count"] == 1
    assert fx.read_customer(b_id)["visible_match_count"] == 1

    as_a, meta_a = validate_paginated(
        api.list_relative_matches(ADMIN, params={"customer_a_id": a_id})
    )
    as_b, meta_b = validate_paginated(
        api.list_relative_matches(ADMIN, params={"customer_b_id": a_id})
    )
    total = meta_a["total_count"] + meta_b["total_count"]
    assert total == 1, f"The pair must not be duplicated; found {total} rows naming A"
    assert len(as_a) + len(as_b) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Family trees
# ═══════════════════════════════════════════════════════════════════════════

def test_tree_person_under_an_unknown_tree_is_rejected(api):
    """PRD §2.5: "Any referenced entity named in the body of a create operation — the subject
    of a subscription, kit, consent grant, family tree, or data request; the instrument of a
    batch; each sample enumerated for a batch; the tree a person joins; the parent links of a
    person; the customer a tree person is linked to — must resolve to an existing record
    before business rules are evaluated."
    PRD §2.5: "Payload-reference failures on subscription creation, kit ordering, batch
    creation, consent granting, tree creation, tree-person creation, and data-request filing
    surface the same 404 family of codes."

    Design: Corner/entities/tree_person_create_under_unknown_tree_returns_tree_not_found
    """
    customer = fx.create_customer(email="tp@dna.test", display_name="TP")
    fx.create_subscription(customer["id"], "FREE")

    resp = api.create_tree_person(
        f.create_tree_person_payload(UNKNOWN_UUID, given_name="Ghost", surname="Nobody"),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TREE_NOT_FOUND.value, 404)


def test_free_tier_tree_rejects_a_fourth_person(api):
    """PRD §3.9: "The **tier person limit**: the tree's `person_count` — which counts only
    the tree's `ACTIVE` people — plus the one being added must not exceed the limit granted
    by the owner's subscription tier. That limit is 3 people on `FREE`, 250 on `PLUS`, and
    999999 on `PRO`. Exceeding it is `ERR_TREE_PERSON_LIMIT` (HTTP 422)."

    Design: Corner/validations/tree_person_limit_exceeded_on_free_tier
    """
    fx.set_clock(CLOCK_START)
    setup = fx.setup_free_tier_tree_at_limit(email="lim@dna.test")
    tree_id = setup["tree"]["id"]
    headers = setup["headers"]
    assert setup["tree"]["person_count"] == 3

    resp = api.create_tree_person(
        f.create_tree_person_payload(tree_id, given_name="Four", surname="Dd"), headers
    )
    validate_error(resp, ApiErrorId.ERR_TREE_PERSON_LIMIT.value, 422)

    assert fx.read_tree(tree_id, setup["customer"]["id"])["person_count"] == 3
    _people, meta = validate_paginated(api.list_tree_people(headers, params={"tree_id": tree_id}))
    assert meta["total_count"] == 3


def test_a_parent_link_into_another_tree_is_rejected_as_a_cycle_violation(api):
    """PRD §3.9: "The **cycle rule**: a `father_id` or `mother_id` must point at a person in
    the same tree, and must not make the new person its own ancestor by any path through the
    parent graph. Either violation is `ERR_TREE_CYCLE` (HTTP 422)."

    Design: Corner/validations/tree_person_self_ancestor_link_returns_tree_cycle
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="cyc@dna.test", display_name="Cyc")
    fx.create_subscription(customer["id"], "PLUS")
    headers = make_customer_headers(customer["id"])

    _tree_a, person_a = fx.create_tree_with_root(customer["id"], "Tree A", surname="Alpha")
    tree_b = validate_success(
        api.create_family_tree(f.create_family_tree_payload(customer["id"], name="Tree B"), headers),
        201,
    )

    resp = api.create_tree_person(
        f.create_tree_person_payload(
            tree_b["id"], given_name="PB", surname="Beta", father_id=person_a["id"]
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_TREE_CYCLE.value, 422)

    assert fx.read_tree(tree_b["id"], customer["id"])["person_count"] == 0
