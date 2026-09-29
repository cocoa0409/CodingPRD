"""Composite environment builders.

The server is restarted before every test, so each test starts with an empty
store and the logical clock at its boot instant. Every precondition below is
therefore built from scratch through the documented endpoints only — there is no
direct store access anywhere in this file.

Each builder routes its setup calls through get_success_data(), so a broken
precondition surfaces as a setup failure at the exact call that broke rather
than as a confusing assertion much later in the test.

Builders are grouped by how much of the platform they stand up: single
transitions first, then entity graphs, then whole-lifecycle shortcuts, then
accumulation targets that sit one step away from a threshold, and finally
terminal states.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    ADMIN,
    ANALYST,
    ENGINEER,
    GOVERNANCE,
    PRIVACY,
    STEWARD,
    make_destination_platform_headers,
)


# --------------------------------------------------------------------------
# low-level helpers
# --------------------------------------------------------------------------
def created(response) -> Dict[str, Any]:
    """The resource returned by a creation call, which answers HTTP 201."""
    return get_success_data(response, expected_status=201)


def acted(response) -> Dict[str, Any]:
    """The resource returned by a transition or a read, which answers HTTP 200."""
    return get_success_data(response, expected_status=200)


def rows(response) -> List[Dict[str, Any]]:
    """The list payload of a collection read."""
    return get_success_data(response, expected_status=200)


def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    """Move the logical clock, which every expiry and window comparison reads."""
    return acted(api.set_clock(f.clock_payload(instant), ADMIN))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    """Return the logical clock to the instant the server boots at."""
    return set_clock(api, DEFAULT_CLOCK)


def retention_run(api: ApiClient) -> Dict[str, Any]:
    """Trigger the four retention steps; the run report answers HTTP 201."""
    return created(api.run_retention(ADMIN))


def reread_profile(api: ApiClient, profile_id: str) -> Dict[str, Any]:
    return acted(api.get_profile(profile_id, ADMIN))


def reread_segment(api: ApiClient, segment_id: str) -> Dict[str, Any]:
    return acted(api.get_segment(segment_id, ADMIN))


def reread_destination(api: ApiClient, destination_id: str) -> Dict[str, Any]:
    return acted(api.get_destination(destination_id, ADMIN))


def reread_activation(api: ApiClient, activation_id: str) -> Dict[str, Any]:
    return acted(api.get_activation(activation_id, ADMIN))


def reread_link(api: ApiClient, link_id: str) -> Dict[str, Any]:
    return acted(api.get_identity_link(link_id, ADMIN))


def reread_rule(api: ApiClient, rule_id: str) -> Dict[str, Any]:
    return acted(api.get_match_rule(rule_id, ADMIN))


def reread_batch(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    return acted(api.get_ingest_batch(batch_id, ADMIN))


def reread_feed(api: ApiClient, source_system_id: str) -> Dict[str, Any]:
    return acted(api.get_source_system(source_system_id, ADMIN))


def reread_deletion_request(api: ApiClient, deletion_request_id: str) -> Dict[str, Any]:
    return acted(api.get_deletion_request(deletion_request_id, ADMIN))


def reread_household(api: ApiClient, household_id: str) -> Dict[str, Any]:
    return acted(api.get_household(household_id, ADMIN))


# --------------------------------------------------------------------------
# tier 1 — single state transitions
# --------------------------------------------------------------------------
def register_feed(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A freshly registered feed, which is REGISTERED and may already ingest."""
    return created(api.create_source_system(f.source_system_payload(**overrides), ADMIN))


def submit_batch(
    api: ApiClient,
    source_system_id: str,
    records: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A batch in RECEIVED, scored by nothing yet."""
    payload = f.ingest_batch_payload(source_system_id, records, **overrides)
    return created(api.create_ingest_batch(payload, ENGINEER))


def received_batch(
    api: ApiClient,
    records: Optional[List[Dict[str, Any]]] = None,
    feed_overrides: Optional[Dict[str, Any]] = None,
    **batch_overrides: Any,
) -> Dict[str, Any]:
    """A feed plus one of its batches sitting in RECEIVED."""
    feed = register_feed(api, **(feed_overrides or {}))
    batch = submit_batch(api, feed["id"], records, **batch_overrides)
    return {"feed": feed, "batch": batch}


def validate(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    return acted(api.validate_batch(batch_id, ENGINEER))


def validated_batch(
    api: ApiClient,
    records: Optional[List[Dict[str, Any]]] = None,
    feed_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A feed plus a batch that has passed the completeness floor."""
    env = received_batch(api, records, feed_overrides)
    env["batch"] = validate(api, env["batch"]["id"])
    return env


# A record on which only the email component passes, so the weighted score is
# 0.30 and the batch falls under the default 0.70 completeness floor.
def failing_record(external_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    blanked: Dict[str, Any] = {
        "phone_raw": None,
        "loyalty_number": None,
        "postal_code": None,
        "first_name": None,
        "last_name": None,
    }
    blanked.update(overrides)
    return f.raw_record(external_id, **blanked)


def quarantined_batch(
    api: ApiClient,
    record_count: int = 1,
    feed_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A feed plus a batch driven QUARANTINED by a score below the floor."""
    records = [failing_record() for _ in range(record_count)]
    return validated_batch(api, records, feed_overrides)


def promote(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    return acted(api.promote_batch(batch_id, ENGINEER))


def batch_profiles(api: ApiClient, batch_id: str) -> List[Dict[str, Any]]:
    """The profiles a promotion minted, read back through the origin-batch filter."""
    return rows(
        api.list_profiles(ADMIN, {"origin_batch_id": batch_id, "limit": 100, "offset": 0})
    )


# --------------------------------------------------------------------------
# tier 2 — the profile graph
# --------------------------------------------------------------------------
def promoted_batch(
    api: ApiClient,
    records: Optional[List[Dict[str, Any]]] = None,
    feed_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A feed driven all the way to ACTIVE by a promotion, with its profiles.

    Register, submit, validate and promote in that order, then read the minted
    profiles back through the origin-batch filter. No match rule exists unless
    the caller declared one first, so each valid record mints its own profile.
    """
    env = validated_batch(api, records, feed_overrides)
    env["batch"] = promote(api, env["batch"]["id"])
    env["feed"] = reread_feed(api, env["feed"]["id"])
    env["profiles"] = batch_profiles(api, env["batch"]["id"])
    return env


def single_profile(
    api: ApiClient,
    record_overrides: Optional[Dict[str, Any]] = None,
    feed_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One promoted profile, RESOLVED and NORMAL, carrying every identifier."""
    record = f.raw_record(**(record_overrides or {}))
    env = promoted_batch(api, [record], feed_overrides)
    assert len(env["profiles"]) == 1, (
        f"setup expected one minted profile, got {len(env['profiles'])}"
    )
    env["profile"] = env["profiles"][0]
    return env


def emailable_profile(
    api: ApiClient,
    record_overrides: Optional[Dict[str, Any]] = None,
    feed_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A promoted profile reachable on EMAIL, carrying an opt-in captured at ingest.

    The record's consent_signals are materialised by promotion into a marketing
    election, so the profile's activatable_channels contains EMAIL and it can
    satisfy an email destination's hashing contract.
    """
    overrides = dict(record_overrides or {})
    overrides.setdefault("consent_signals", list(f.EMAIL_OPT_IN))
    return single_profile(api, overrides, feed_overrides)


def emailable_profiles(
    api: ApiClient,
    count: int,
    feed_overrides: Optional[Dict[str, Any]] = None,
    record_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Several distinct promoted profiles, each reachable on EMAIL.

    Every record carries its own identifiers so no deterministic key is shared,
    and they all sit in postal code 10001 so one postal predicate selects them
    all.
    """
    records = []
    for _ in range(count):
        overrides = dict(record_overrides or {})
        overrides.setdefault("consent_signals", list(f.EMAIL_OPT_IN))
        records.append(f.raw_record(**overrides))
    env = promoted_batch(api, records, feed_overrides)
    assert len(env["profiles"]) == count, (
        f"setup expected {count} minted profiles, got {len(env['profiles'])}"
    )
    return env


def two_profiles(
    api: ApiClient,
    feed_overrides: Optional[Dict[str, Any]] = None,
    left_overrides: Optional[Dict[str, Any]] = None,
    right_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Two promoted profiles with no link between them.

    Both are RESOLVED because no probabilistic rule existed during promotion, so
    a link proposed afterwards is the only link in the store.
    """
    left = f.raw_record(**(left_overrides or {}))
    right = f.raw_record(**(right_overrides or {}))
    env = promoted_batch(api, [left, right], feed_overrides)
    assert len(env["profiles"]) == 2, (
        f"setup expected two minted profiles, got {len(env['profiles'])}"
    )
    ordered = sorted(env["profiles"], key=lambda p: p["created_at"])
    env["left"], env["right"] = ordered[0], ordered[1]
    return env


def profile_with_address(
    api: ApiClient,
    address_line: str = "12 Alpha Street",
    record_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One promoted profile that promotion has already placed in a household."""
    overrides = dict(record_overrides or {})
    overrides["address_line"] = address_line
    env = single_profile(api, overrides)
    env["household_id"] = env["profile"]["household_id"]
    return env


def profiles_at_address(
    api: ApiClient, count: int, address_line: str = "12 Alpha Street"
) -> Dict[str, Any]:
    """Several promoted profiles sharing one address, filling the overflow buckets.

    The grouping waterfall runs inside the promotion, so the first six profiles
    land in bucket 1 and the seventh opens bucket 2.
    """
    records = [f.raw_record(address_line=address_line) for _ in range(count)]
    env = promoted_batch(api, records)
    env["households"] = rows(
        api.list_households(ADMIN, {"limit": 100, "offset": 0})
    )
    return env


def declare_probabilistic_rule(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A probabilistic rule declared after promotion, so it minted nothing itself."""
    return created(api.create_match_rule(f.probabilistic_rule_payload(**overrides), ADMIN))


def declare_deterministic_rule(
    api: ApiClient, deterministic_key: str = "EMAIL_NORM", **overrides: Any
) -> Dict[str, Any]:
    return created(
        api.create_match_rule(
            f.deterministic_rule_payload(deterministic_key, **overrides), ADMIN
        )
    )


def proposed_link(
    api: ApiClient,
    left_profile_id: str,
    right_profile_id: str,
    match_rule_id: str,
    evidence_values: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A candidate link awaiting a steward, minted from explicit evidence."""
    payload = f.identity_link_payload(
        left_profile_id, right_profile_id, match_rule_id, evidence_values
    )
    return created(api.create_identity_link(payload, STEWARD))


def decide_link(api: ApiClient, link_id: str, decision: str) -> Dict[str, Any]:
    return acted(
        api.decide_identity_link(link_id, f.link_decision_payload(decision), STEWARD)
    )


def review_band_link_environment(
    api: ApiClient,
    rule_overrides: Optional[Dict[str, Any]] = None,
    evidence_values: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Two profiles, one probabilistic rule and one PROPOSED link between them.

    The evidence is chosen to land inside the rule's review band, so the link
    waits for an adjudication rather than confirming itself.
    """
    env = two_profiles(api)
    env["rule"] = declare_probabilistic_rule(api, **(rule_overrides or {}))
    env["link"] = proposed_link(
        api,
        env["left"]["id"],
        env["right"]["id"],
        env["rule"]["id"],
        evidence_values if evidence_values is not None else f.evidence(
            email_similarity=1.0,
            phone_similarity=1.0,
            name_similarity=0.0,
            address_similarity=0.0,
        ),
    )
    return env


def capture_consent(
    api: ApiClient,
    profile_id: str,
    source_system_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Capture one election, reading the subject's live version for the guard."""
    profile = reread_profile(api, profile_id)
    payload = f.consent_record_payload(
        profile_id, source_system_id, profile["version"], **overrides
    )
    return created(api.create_consent_record(payload, PRIVACY))


def add_suppression(api: ApiClient, profile_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        api.create_suppression_entry(f.suppression_entry_payload(profile_id, **overrides), PRIVACY)
    )


def release_suppression(api: ApiClient, suppression_id: str, headers=None) -> Dict[str, Any]:
    """Release an entry; a legal hold demands an officer other than its author."""
    return acted(api.release_suppression_entry(suppression_id, headers or PRIVACY))


# --------------------------------------------------------------------------
# tier 3 — whole-lifecycle shortcuts
# --------------------------------------------------------------------------
def draft_segment(
    api: ApiClient,
    criteria: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A DRAFT segment whose member count was computed on creation."""
    return created(api.create_segment(f.segment_payload(criteria, **overrides), ANALYST))


def submit_segment(api: ApiClient, segment_id: str, headers=None) -> Dict[str, Any]:
    return acted(api.submit_segment_for_review(segment_id, headers or ANALYST))


def decide_segment(
    api: ApiClient,
    segment_id: str,
    decision: str = "APPROVE",
    sensitive_use_approved: Optional[bool] = False,
    headers=None,
) -> Dict[str, Any]:
    payload = f.governance_decision_payload(decision, sensitive_use_approved)
    return acted(api.decide_segment_governance(segment_id, payload, headers or GOVERNANCE))


def approved_segment(
    api: ApiClient,
    criteria: Optional[List[Dict[str, Any]]] = None,
    sensitive_use_approved: bool = False,
    segment_overrides: Optional[Dict[str, Any]] = None,
    **create_overrides: Any,
) -> Dict[str, Any]:
    """A segment carried DRAFT to APPROVED through the review loop.

    The analyst authors and submits, and a different officer decides, so the
    segregation-of-duties check on the decision is satisfied.
    """
    overrides = dict(segment_overrides or {})
    overrides.update(create_overrides)
    segment = draft_segment(api, criteria, **overrides)
    submit_segment(api, segment["id"])
    return decide_segment(api, segment["id"], "APPROVE", sensitive_use_approved)


def approved_sensitive_segment(
    api: ApiClient,
    criteria: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An approved segment built on a sensitive attribute, with its use affirmed."""
    sensitive_criteria = criteria if criteria is not None else [
        f.criterion("inferred_health_interest", "EQ", "FITNESS")
    ]
    overrides.setdefault(
        "governance_justification",
        "Health interest audience approved for a wellness campaign.",
    )
    return approved_segment(
        api, sensitive_criteria, sensitive_use_approved=True, **overrides
    )


def register_destination(
    api: ApiClient, permissive: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """An ACTIVE destination whose full quota is available on registration.

    The permissive variant lowers the k-anonymity floor, the match-rate floor and
    the cooldown so that a one-member audience can be delivered without those
    three limits interfering.
    """
    payload = (
        f.permissive_destination_payload(**overrides)
        if permissive
        else f.destination_payload(**overrides)
    )
    return created(api.create_destination(payload, ADMIN))


def draft_activation(
    api: ApiClient,
    segment_id: str,
    destination_id: str,
    window_start_at: str = "2026-08-02T00:00:00Z",
    window_end_at: str = "2026-08-02T02:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A DRAFT activation created under the segment's live version guard."""
    segment = reread_segment(api, segment_id)
    payload = f.activation_payload(
        segment_id,
        destination_id,
        segment["version"],
        window_start_at,
        window_end_at,
        **overrides,
    )
    return created(api.create_activation(payload, ANALYST))


def dispatch(api: ApiClient, activation_id: str) -> Dict[str, Any]:
    return acted(api.dispatch_activation(activation_id, ANALYST))


def pause(api: ApiClient, activation_id: str) -> Dict[str, Any]:
    return acted(api.pause_activation(activation_id, ANALYST))


def resume(api: ApiClient, activation_id: str) -> Dict[str, Any]:
    return acted(api.resume_activation(activation_id, ANALYST))


def report_match(
    api: ApiClient,
    activation_id: str,
    destination_id: str,
    vendor_matched_count: int,
    unusable_hash_count: int = 0,
    attributed_conversions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A report filed by the destination platform actor that owns the activation."""
    payload = f.match_report_payload(
        vendor_matched_count, unusable_hash_count, attributed_conversions
    )
    return acted(
        api.report_match(
            activation_id, payload, make_destination_platform_headers(destination_id)
        )
    )


def activation_ready_environment(
    api: ApiClient,
    member_count: int = 1,
    destination_overrides: Optional[Dict[str, Any]] = None,
    segment_criteria: Optional[List[Dict[str, Any]]] = None,
    window_start_at: str = "2026-08-02T00:00:00Z",
    window_end_at: str = "2026-08-02T02:00:00Z",
) -> Dict[str, Any]:
    """Everything a dispatch needs: emailable members, an approved segment,
    an active destination and a DRAFT activation.

    Every member is reachable on EMAIL and carries an email_norm, so the whole
    audience produces a hash under the destination's email hashing contract.
    """
    env = emailable_profiles(api, member_count)
    env["segment"] = approved_segment(
        api, segment_criteria if segment_criteria is not None else list(f.POSTAL_10001)
    )
    env["destination"] = register_destination(api, **(destination_overrides or {}))
    env["activation"] = draft_activation(
        api,
        env["segment"]["id"],
        env["destination"]["id"],
        window_start_at,
        window_end_at,
    )
    return env


def delivering_activation_environment(
    api: ApiClient,
    member_count: int = 1,
    destination_overrides: Optional[Dict[str, Any]] = None,
    segment_criteria: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """An activation carried all the way to DISPATCHED, holding quota."""
    env = activation_ready_environment(
        api, member_count, destination_overrides, segment_criteria
    )
    env["activation"] = dispatch(api, env["activation"]["id"])
    env["destination"] = reread_destination(api, env["destination"]["id"])
    env["segment"] = reread_segment(api, env["segment"]["id"])
    return env


def reported_activation_environment(
    api: ApiClient,
    member_count: int = 1,
    vendor_matched_count: int = 1,
    unusable_hash_count: int = 0,
    destination_overrides: Optional[Dict[str, Any]] = None,
    attributed_conversions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A dispatched activation that has received one match report."""
    env = delivering_activation_environment(
        api, member_count, destination_overrides
    )
    env["activation"] = report_match(
        api,
        env["activation"]["id"],
        env["destination"]["id"],
        vendor_matched_count,
        unusable_hash_count,
        attributed_conversions,
    )
    env["destination"] = reread_destination(api, env["destination"]["id"])
    return env


def attribution_environment(
    api: ApiClient,
    member_count: int = 3,
    revenue_cents: int = 100,
    converted_at: str = "2026-08-02T01:00:00Z",
    conversions_per_member: int = 1,
    destination_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A delivered segment carrying one conversion per member.

    Each conversion is dated after the segment's approval instant, so all of them
    qualify for the attribution window, and revenue is reported in whole cents as
    a JSON number.
    """
    env = delivering_activation_environment(
        api, member_count, destination_overrides
    )
    conversions: List[Dict[str, Any]] = []
    for profile in env["profiles"]:
        for index in range(conversions_per_member):
            conversions.append(
                f.conversion(
                    profile["id"],
                    converted_at if index == 0 else "2026-08-02T01:30:00Z",
                    revenue_cents,
                )
            )
    env["conversions"] = conversions
    env["activation"] = report_match(
        api,
        env["activation"]["id"],
        env["destination"]["id"],
        member_count,
        0,
        conversions,
    )
    env["segment"] = reread_segment(api, env["segment"]["id"])
    return env


# --------------------------------------------------------------------------
# tier 4 — accumulation and threshold targets
# --------------------------------------------------------------------------
def quarantined_feed(api: ApiClient, record_count: int = 5) -> Dict[str, Any]:
    """A feed driven QUARANTINED on cumulative evidence.

    Five in-window records is already enough evidence to act on, and every one of
    them scores below the record minimum, so the recomputed pass rate falls under
    the feed's own completeness floor.
    """
    records = [failing_record() for _ in range(record_count)]
    env = received_batch(api, records)
    env["batch"] = validate(api, env["batch"]["id"])
    env["feed"] = reread_feed(api, env["feed"]["id"])
    return env


def batch_at_retry_budget(api: ApiClient) -> Dict[str, Any]:
    """A QUARANTINED batch whose retry_round has reached the budget of two.

    One failing record keeps the feed's in-window total below the five-record
    evidence threshold, so the feed itself never quarantines and the batch can be
    cycled twice without the cascade interfering.
    """
    env = quarantined_batch(api, record_count=1)
    batch_id = env["batch"]["id"]
    for _ in range(2):
        acted(api.requeue_batch(batch_id, ENGINEER))
        validate(api, batch_id)
    env["batch"] = reread_batch(api, batch_id)
    assert env["batch"]["retry_round"] == 2, (
        f"setup expected retry_round 2, got {env['batch']['retry_round']}"
    )
    return env


def merged_pair(
    api: ApiClient,
    left_overrides: Optional[Dict[str, Any]] = None,
    right_overrides: Optional[Dict[str, Any]] = None,
    rule_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Two profiles merged by a link that confirmed itself on the spot.

    Perfect evidence on all four components scores the full weight base, which is
    at or above the rule's merge threshold, so the link is confirmed inside the
    creating call and the merge runs there.
    """
    env = two_profiles(api, None, left_overrides, right_overrides)
    env["rule"] = declare_probabilistic_rule(api, **(rule_overrides or {}))
    env["link"] = proposed_link(
        api,
        env["left"]["id"],
        env["right"]["id"],
        env["rule"]["id"],
        f.evidence(1.0, 1.0, 1.0, 1.0),
    )
    link = env["link"]
    assert link["status"] == "CONFIRMED", (
        f"setup expected an auto-confirmed link, got {link['status']}"
    )
    survivor_id = link["survivor_profile_id"]
    loser_id = (
        env["right"]["id"] if survivor_id == env["left"]["id"] else env["left"]["id"]
    )
    env["survivor"] = reread_profile(api, survivor_id)
    env["loser"] = reread_profile(api, loser_id)
    return env


def profile_with_value(
    api: ApiClient, revenue_cents: int, member_count: int = 1
) -> Dict[str, Any]:
    """A profile whose lifetime value has been raised by a reported conversion."""
    env = delivering_activation_environment(api, member_count)
    target = env["profiles"][0]
    env["activation"] = report_match(
        api,
        env["activation"]["id"],
        env["destination"]["id"],
        member_count,
        0,
        [f.conversion(target["id"], "2026-08-02T01:00:00Z", revenue_cents)],
    )
    env["profile"] = reread_profile(api, target["id"])
    return env


# --------------------------------------------------------------------------
# tier 5 — terminal and finalised states
# --------------------------------------------------------------------------
def record_erasure(api: ApiClient, profile_id: str, **overrides: Any) -> Dict[str, Any]:
    """Record an erasure request, driving the subject to DELETION_PENDING."""
    return created(
        api.create_deletion_request(f.deletion_request_payload(profile_id, **overrides), PRIVACY)
    )


def propagate(api: ApiClient, deletion_request_id: str) -> Dict[str, Any]:
    """Fan an erasure out under the request's live version guard."""
    request = reread_deletion_request(api, deletion_request_id)
    payload = f.propagate_payload(request["version"])
    return acted(api.propagate_deletion_request(deletion_request_id, payload, PRIVACY))


def pending_erasure(api: ApiClient) -> Dict[str, Any]:
    """A subject in DELETION_PENDING with its erasure request in RECEIVED.

    No destination has ever taken a delivery, so nothing downstream qualifies for
    fan-out yet.
    """
    env = single_profile(api)
    env["request"] = record_erasure(api, env["profile"]["id"])
    env["profile"] = reread_profile(api, env["profile"]["id"])
    return env


def verified_erasure(api: ApiClient) -> Dict[str, Any]:
    """An erasure completed inside its own propagate call, with no vendor task.

    Zero destinations qualify, so there is nothing downstream to verify and the
    subject is tombstoned immediately.
    """
    env = pending_erasure(api)
    env["request"] = propagate(api, env["request"]["id"])
    env["profile"] = reread_profile(api, env["profile"]["id"])
    return env


def propagating_erasure(api: ApiClient, member_count: int = 2) -> Dict[str, Any]:
    """An erasure fanned out to one destination that has taken a delivery.

    A destination qualifies for fan-out once it is active and holds at least one
    activation that is not a draft, which the dispatch below arranges.
    """
    env = delivering_activation_environment(api, member_count)
    subject = env["profiles"][0]
    env["subject"] = subject
    env["request"] = record_erasure(api, subject["id"])
    env["request"] = propagate(api, env["request"]["id"])
    env["tasks"] = rows(
        api.list_vendor_tasks(
            ADMIN, {"deletion_request_id": env["request"]["id"], "limit": 100, "offset": 0}
        )
    )
    env["profile"] = reread_profile(api, subject["id"])
    return env


def legal_hold_over_pending_erasure(api: ApiClient) -> Dict[str, Any]:
    """A stored legal hold outranked on the privacy axis by a pending erasure.

    The hold is raised on a subject already in DELETION_PENDING, so it is stored
    ACTIVE while the privacy axis stays where it was, and it is the only route by
    which a fan-out is ever blocked.
    """
    env = pending_erasure(api)
    env["hold"] = add_suppression(
        api,
        env["profile"]["id"],
        entry_type="LEGAL_HOLD",
        reason_code="LITIGATION_HOLD",
    )
    env["profile"] = reread_profile(api, env["profile"]["id"])
    return env


def timed_out_vendor_task(api: ApiClient, member_count: int = 2) -> Dict[str, Any]:
    """A dispatched vendor task carried past its acknowledgement deadline.

    The clock is moved beyond the destination's acknowledgement SLA and a
    retention run then times the task out, leaving its parent request partially
    verified.
    """
    env = propagating_erasure(api, member_count)
    assert env["tasks"], "setup expected at least one vendor deletion task"
    task = env["tasks"][0]
    set_clock(api, "2026-08-10T00:00:00Z")
    env["run"] = retention_run(api)
    env["task"] = acted(api.get_vendor_task(task["id"], ADMIN))
    env["request"] = reread_deletion_request(api, env["request"]["id"])
    return env


def acknowledge_task(
    api: ApiClient, task_id: str, destination_id: str, outcome: str = "ACKNOWLEDGED", **overrides
) -> Dict[str, Any]:
    """Acknowledge a task as the destination platform actor that owns it."""
    return acted(
        api.acknowledge_vendor_task(
            task_id,
            f.vendor_ack_payload(outcome, **overrides),
            make_destination_platform_headers(destination_id),
        )
    )


def retired_segment(api: ApiClient) -> Dict[str, Any]:
    """A segment retired while one of its activations was still delivering."""
    env = delivering_activation_environment(api)
    env["segment"] = acted(api.retire_segment(env["segment"]["id"], GOVERNANCE))
    env["activation"] = reread_activation(api, env["activation"]["id"])
    env["destination"] = reread_destination(api, env["destination"]["id"])
    return env


def short_governance_environment(api: ApiClient, valid_days: int = 1) -> Dict[str, Any]:
    """A delivering activation whose segment approval lasts only a day or two."""
    env = emailable_profiles(api, 1)
    env["segment"] = approved_segment(
        api, list(f.POSTAL_10001), governance_valid_days=valid_days
    )
    env["destination"] = register_destination(api)
    env["activation"] = draft_activation(
        api, env["segment"]["id"], env["destination"]["id"]
    )
    env["activation"] = dispatch(api, env["activation"]["id"])
    env["destination"] = reread_destination(api, env["destination"]["id"])
    env["segment"] = reread_segment(api, env["segment"]["id"])
    return env
