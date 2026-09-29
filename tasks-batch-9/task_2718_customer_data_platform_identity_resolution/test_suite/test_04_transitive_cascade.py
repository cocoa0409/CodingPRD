"""Multi-hop cascades that must run to their full depth inside one call.

Two independent chains are exercised. A steward's REJECT drops a rule's precision
estimate below its own floor, which disables the rule, which voids the rule's
other outstanding candidate link — three hops, none of them touching a profile. A
destination platform's acknowledgement completes an erasure, which tombstones the
subject, which tombstones its consent election, voids its candidate link and
dissolves its household — four hops, all of them on the privacy axis.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    approx4,
    assert_activatable,
    assert_instant_equals,
    assert_profile_axes,
    assert_task_counters,
    assert_tombstoned_identifiers,
)
from test_helpers.test_users import ADMIN, PRIVACY, STEWARD

# Three components matched exactly with the address absent on at least one side.
# Under STRICT_ZERO that is 0.40 + 0.25 + 0.20 = 0.8500, which sits inside the
# review band of a rule whose review_floor is 0.65 and whose auto_merge_threshold
# is 0.92, so the link waits for a steward rather than confirming itself.
SPARSE_PERFECT_EVIDENCE = dict(
    email_similarity=1.0,
    phone_similarity=1.0,
    name_similarity=1.0,
    address_similarity=None,
)
BOOT_INSTANT = "2026-08-01T00:00:00Z"


def _reject_cascade_environment(api):
    """Four promoted profiles, one rule at the default 0.60 precision floor, and
    two candidate links minted by that rule over disjoint pairs.

    The rule has decided nothing yet, so its precision_estimate is 1.0 and its
    status is ENABLED; a single rejection is therefore enough to take the estimate
    to 0.0000 and drive the whole chain.
    """
    records = [f.raw_record() for _ in range(4)]
    env = fx.promoted_batch(api, records)
    assert len(env["profiles"]) == 4, (
        f"setup expected four minted profiles, got {len(env['profiles'])}"
    )
    env["p1"], env["p2"], env["p3"], env["p4"] = env["profiles"]
    env["rule"] = fx.declare_probabilistic_rule(api, min_precision=0.60)
    env["target"] = fx.proposed_link(
        api,
        env["p1"]["id"],
        env["p2"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    env["sibling"] = fx.proposed_link(
        api,
        env["p3"]["id"],
        env["p4"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    assert env["target"]["status"] == "PROPOSED"
    assert env["sibling"]["status"] == "PROPOSED"
    return env


def test_reject_lowers_precision_disables_the_rule_and_voids_the_sibling_link(api):
    """One rejection drives a three-hop chain: the rule's precision falls to
    0.0000, which is strictly below its min_precision of 0.60, so the rule is
    disabled, and the disabling voids the rule's other outstanding candidate.

    "Instead the rule's `rejected_count` increases by 1 and `precision_estimate` is recomputed as `confirmed_count` divided by the sum of `confirmed_count` and `rejected_count`, rounded half up to four decimal places, and held at exactly 1.0 while that denominator is 0."

    "Where the recomputed estimate falls strictly below the rule's own `min_precision`, hop two moves the rule `ENABLED` → `DISABLED`, and hop three voids every **other** link minted by that rule whose status is still `PROPOSED`, each with `void_reason` of `RULE_DISABLED`."

    "Where this document describes a cascade in hops, every hop runs, in the order given, inside the originating call, and each resource a hop mutates has its `updated_at` refreshed and its `version` incremented by 1."

    Design: Difficulty/transitive_cascade/reject_lowers_precision_disables_rule_voids_sibling_link
    """
    env = _reject_cascade_environment(api)

    decided = fx.decide_link(api, env["target"]["id"], "REJECT")
    assert decided["status"] == "REJECTED"
    assert decided["decided_by_user_id"] == STEWARD["X-User-ID"]
    assert_instant_equals(decided["decided_at"], BOOT_INSTANT, "decided_at")

    rule = fx.reread_rule(api, env["rule"]["id"])
    assert rule["rejected_count"] == 1
    assert rule["confirmed_count"] == 0
    assert rule["precision_estimate"] == approx4(0.0)
    assert rule["status"] == "DISABLED"

    sibling = fx.reread_link(api, env["sibling"]["id"])
    assert sibling["status"] == "VOIDED"
    assert sibling["void_reason"] == "RULE_DISABLED"


def test_the_voided_sibling_is_neither_decided_nor_counted_by_the_rule(api):
    """The voided sibling is not an adjudication: it carries no survivor and no
    decision audit, and the voiding leaves the rule's two counters exactly where
    the single rejection put them.

    "Voiding never touches the rule's counters — a voided link is neither a confirmation nor a rejection, and so cannot itself move the precision estimate."

    "This is a **branching fork**: the two branches share no side effect beyond the link's own status, `decided_by_user_id` (set to the acting `X-User-ID`), `decided_at` and its `version` increment."

    Design: Difficulty/transitive_cascade/reject_lowers_precision_disables_rule_voids_sibling_link
    """
    env = _reject_cascade_environment(api)

    fx.decide_link(api, env["target"]["id"], "REJECT")

    sibling = fx.reread_link(api, env["sibling"]["id"])
    assert sibling["status"] == "VOIDED"
    assert sibling["void_reason"] == "RULE_DISABLED"
    assert sibling["survivor_profile_id"] is None
    assert sibling["decided_by_user_id"] is None
    assert sibling["decided_at"] is None

    rule = fx.reread_rule(api, env["rule"]["id"])
    assert rule["rejected_count"] == 1, (
        "the voided sibling must not be counted as a second rejection"
    )
    assert rule["confirmed_count"] == 0
    assert rule["precision_estimate"] == approx4(0.0)

    # The rejected link itself is REJECTED, not swept up in the void hop.
    target = fx.reread_link(api, env["target"]["id"])
    assert target["status"] == "REJECTED"
    assert target["void_reason"] is None


def test_no_profile_is_mutated_anywhere_in_the_reject_cascade(api):
    """All four endpoint profiles of the two links stand untouched: the chain runs
    entirely across the link and rule entities and merges nobody.

    "No profile is mutated: `survivor_profile_id` stays null and both profiles keep `resolution_status` of `RESOLVED`."

    "The confirm branch additionally requires both profiles to be `RESOLVED` and neither to be under `LEGAL_HOLD`, `DELETED` or `DELETION_PENDING`; the reject branch imposes no profile condition at all, since it touches no profile."

    Design: Difficulty/transitive_cascade/reject_lowers_precision_disables_rule_voids_sibling_link
    """
    env = _reject_cascade_environment(api)

    fx.decide_link(api, env["target"]["id"], "REJECT")

    for key in ("p1", "p2", "p3", "p4"):
        profile = fx.reread_profile(api, env[key]["id"])
        assert_profile_axes(profile, "RESOLVED", "NORMAL")
        assert profile["source_record_count"] == 1
        assert profile["merged_into_profile_id"] is None
        assert profile["lifetime_value_cents"] == 0


def _erasure_cascade_environment(api):
    """A subject whose erasure is fanned out to one destination and awaits its ack.

    Two profiles are promoted from one batch, each carrying an EMAIL marketing
    opt-in and postal code 10001; only the first carries an address, so exactly one
    household exists and the erasure subject is its only member. A candidate link
    joins the subject to the second profile, an approved segment is delivered to an
    active destination — which is what makes that destination qualify for fan-out —
    and the subject's erasure request is then propagated, leaving one DISPATCHED
    vendor deletion task.
    """
    subject_record = f.raw_record(
        address_line="10 Oak St", consent_signals=list(f.EMAIL_OPT_IN)
    )
    other_record = f.raw_record(consent_signals=list(f.EMAIL_OPT_IN))
    env = fx.promoted_batch(api, [subject_record, other_record])
    assert len(env["profiles"]) == 2, (
        f"setup expected two minted profiles, got {len(env['profiles'])}"
    )
    housed = [p for p in env["profiles"] if p["household_id"] is not None]
    unhoused = [p for p in env["profiles"] if p["household_id"] is None]
    assert len(housed) == 1 and len(unhoused) == 1, (
        "setup expected exactly one profile placed in a household"
    )
    env["subject"] = housed[0]
    env["other"] = unhoused[0]
    env["household_id"] = housed[0]["household_id"]

    elections = fx.rows(
        api.list_consent_records(
            PRIVACY, {"profile_id": env["subject"]["id"], "limit": 100, "offset": 0}
        )
    )
    assert len(elections) == 1, (
        f"setup expected one materialised election, got {len(elections)}"
    )
    env["election"] = elections[0]

    env["rule"] = fx.declare_probabilistic_rule(api, min_precision=0.40)
    env["link"] = fx.proposed_link(
        api,
        env["subject"]["id"],
        env["other"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    assert env["link"]["status"] == "PROPOSED"

    env["destination"] = fx.register_destination(
        api,
        platform_kind="MESSAGING",
        min_audience_size=1,
        daily_hash_quota=100,
        deletion_ack_sla_hours=72,
    )
    env["segment"] = fx.approved_segment(api, list(f.POSTAL_10001))
    env["activation"] = fx.draft_activation(
        api, env["segment"]["id"], env["destination"]["id"]
    )
    env["activation"] = fx.dispatch(api, env["activation"]["id"])
    assert env["activation"]["status"] == "DISPATCHED"

    env["request"] = fx.record_erasure(api, env["subject"]["id"])
    env["request"] = fx.propagate(api, env["request"]["id"])
    assert env["request"]["status"] == "PROPAGATING"

    env["tasks"] = fx.rows(
        api.list_vendor_tasks(
            ADMIN,
            {"deletion_request_id": env["request"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert len(env["tasks"]) == 1, (
        f"setup expected one vendor deletion task, got {len(env['tasks'])}"
    )
    env["task"] = env["tasks"][0]
    assert env["task"]["status"] == "DISPATCHED"
    return env


def test_vendor_acknowledgement_verifies_the_request_and_tombstones_the_subject(api):
    """The only outstanding vendor task is acknowledged, which makes the
    acknowledged count equal the total, which verifies the erasure request, which
    tombstones the subject and nulls its identifiers — hops one through three.

    "A task in `DISPATCHED` or `TIMED_OUT` accepts an `outcome` of either `ACKNOWLEDGED` or `FAILED`, any other value being `ERR_INVALID_REQUEST`, optionally accompanied by a `deletion_evidence_reference` and an `acknowledged_record_count` claiming how many records the platform erased."

    "When `acknowledged_vendor_task_count` equals `total_vendor_task_count`, meaning every platform has confirmed, the request bubbles up to `VERIFIED` — from `PROPAGATING` or, on a late acknowledgement, from `PARTIALLY_VERIFIED` — and `verified_at` is stamped."

    "Reaching `VERIFIED` tombstones the subject, moving it `DELETION_PENDING` → `DELETED`."

    "Seven fields are nulled: `email_norm`, `phone_norm`, `first_name`, `last_name`, `inferred_health_interest`, `inferred_ethnicity_affinity` and `precise_geolocation_grid`."

    Design: Difficulty/transitive_cascade/vendor_ack_verifies_request_tombstones_profile_dissolves_household
    """
    env = _erasure_cascade_environment(api)

    task = fx.acknowledge_task(
        api,
        env["task"]["id"],
        env["destination"]["id"],
        "ACKNOWLEDGED",
        deletion_evidence_reference="VDR-001",
        acknowledged_record_count=1,
    )
    assert task["status"] == "ACKNOWLEDGED"
    assert_instant_equals(task["acknowledged_at"], BOOT_INSTANT, "acknowledged_at")
    assert task["acknowledged_record_count"] == 1

    request = fx.reread_deletion_request(api, env["request"]["id"])
    assert_task_counters(
        request,
        total_vendor_task_count=1,
        acknowledged_vendor_task_count=1,
        pending_vendor_task_count=0,
        failed_vendor_task_count=0,
        timed_out_vendor_task_count=0,
    )
    assert request["status"] == "VERIFIED"
    assert_instant_equals(request["verified_at"], BOOT_INSTANT, "verified_at")

    subject = fx.reread_profile(api, env["subject"]["id"])
    assert subject["privacy_status"] == "DELETED"
    assert_tombstoned_identifiers(subject)
    assert_activatable(subject, [])


def test_the_tombstone_tombstones_consent_voids_the_link_and_dissolves_the_household(api):
    """Hop four fires only because the subject reached DELETED: its election is
    tombstoned, its outstanding candidate link is voided as PROFILE_DELETED, and
    the household it was the sole member of dissolves.

    "Every consent election of the subject becomes `TOMBSTONED` with `precedence_rank` forced to 0, whatever it held before — active, superseded or expired — and `TOMBSTONED` is terminal for an election."

    "Every identity link of the subject still in `PROPOSED` becomes `VOIDED` with `void_reason` of `PROFILE_DELETED`, and any `CONFIRMED` link whose `survivor_profile_id` is this subject is voided the same way while the profile it merged keeps `resolution_status` of `MERGED_AWAY`."

    "The subject is detached from its household, whose `member_count` decrements and which dissolves if that count reaches 0."

    "When a recomputation drives `member_count` to 0, the household moves `ACTIVE` → `DISSOLVED`, its `dominant_last_name` is cleared to null and its `combined_lifetime_value_cents` is reset to 0, and its `version` increments by 1."

    Design: Difficulty/transitive_cascade/vendor_ack_verifies_request_tombstones_profile_dissolves_household
    """
    env = _erasure_cascade_environment(api)

    fx.acknowledge_task(
        api,
        env["task"]["id"],
        env["destination"]["id"],
        "ACKNOWLEDGED",
        deletion_evidence_reference="VDR-001",
        acknowledged_record_count=1,
    )

    election = fx.acted(api.get_consent_record(env["election"]["id"], PRIVACY))
    assert election["status"] == "TOMBSTONED"
    assert election["precedence_rank"] == 0

    link = fx.reread_link(api, env["link"]["id"])
    assert link["status"] == "VOIDED"
    assert link["void_reason"] == "PROFILE_DELETED"

    subject = fx.reread_profile(api, env["subject"]["id"])
    assert subject["household_id"] is None

    household = fx.reread_household(api, env["household_id"])
    assert household["member_count"] == 0
    assert household["status"] == "DISSOLVED"
    assert household["dominant_last_name"] is None
    assert household["combined_lifetime_value_cents"] == 0


def test_the_erasure_cascade_rides_the_privacy_axis_and_spares_the_other_profile(api):
    """The four-hop chain never touches the resolution axis and never reaches the
    profile that was not the erasure subject.

    "The subject's `resolution_status` is left entirely untouched — the two axes are independent, and a deleted profile remembers whether it was ever resolved."

    "A profile carries two independent lifecycle axes on the same row, and the platform must never let one gate the other."

    "Reaching `VERIFIED` tombstones the subject, moving it `DELETION_PENDING` → `DELETED`."

    Design: Difficulty/transitive_cascade/vendor_ack_verifies_request_tombstones_profile_dissolves_household
    """
    env = _erasure_cascade_environment(api)
    before = fx.reread_profile(api, env["subject"]["id"])
    assert_profile_axes(before, "RESOLVED", "DELETION_PENDING")

    fx.acknowledge_task(
        api,
        env["task"]["id"],
        env["destination"]["id"],
        "ACKNOWLEDGED",
        deletion_evidence_reference="VDR-001",
        acknowledged_record_count=1,
    )

    subject = fx.reread_profile(api, env["subject"]["id"])
    assert_profile_axes(subject, "RESOLVED", "DELETED")
    assert subject["merged_into_profile_id"] is None

    other = fx.reread_profile(api, env["other"]["id"])
    assert_profile_axes(other, "RESOLVED", "NORMAL")
    assert_activatable(other, ["EMAIL"])
    assert other["email_norm"] is not None
    assert other["household_id"] is None
