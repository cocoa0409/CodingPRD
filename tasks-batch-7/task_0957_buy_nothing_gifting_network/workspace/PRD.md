# Buy Nothing Gifting Network API — Product Requirements Document

## 1. Introduction

Buy-nothing communities thrive on a simple social contract: neighbors give freely, receivers show up, and nobody sells anything. In practice, that contract frays quickly — popular items attract a pile-up of competing claimants, pickup arrangements stall in endless back-and-forth, no-shows erode trust, and a small number of bad actors can poison an otherwise generous group. This document specifies the Buy Nothing Gifting Network API, a platform that makes the social contract enforceable in software: items are offered inside geographically anchored neighborhood groups, demand is organized into a fair claim queue with three selectable promotion policies, porch pickups are coordinated through a bounded negotiation protocol, and a moderation pipeline with strike thresholds, suspensions, and bans keeps the network healthy.

The API serves four constituencies. Ordinary members give and receive items, maintain wishlists, and post curb alerts for free-cycle-style curbside events. Group moderators — themselves members, elevated per group — approve join requests, review reports, and apply sanctions. Platform administrators operate above any single group: they create the geo-groups, overturn moderation actions, and drive the logical clock that governs every time-based behavior in the system. Unauthenticated visitors may do exactly one thing: register.

Everything time-dependent in the network — offer expiry, post expiry, wishlist expiry, reputation settlement, strike ageing, suspension reinstatement, curb-alert activation — is evaluated against a single server-side logical clock rather than wall-clock time. This design makes every temporal rule in this document deterministic and testable, and it is a hard requirement, not an implementation detail.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The platform recognizes four roles, spelled exactly as follows: `Anonymous`, `Member`, `GroupModerator`, and `PlatformAdmin`. A request with missing or malformed headers is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member compare the resource's foreign-key field (for example a post's `giver_id` or a claim's `claimer_id`) to `X-User-ID`. When `X-User-Role` is `GroupModerator`, `X-User-ID` is likewise the `id` of a `Member` — the member whose membership carries moderator authority — and the role is only honored when that member holds an `APPROVED` `GroupMembership` with `role` equal to `MODERATOR` in the group the operation targets; a moderator acting in a group they do not moderate is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `Anonymous` or `PlatformAdmin`, `X-User-ID` is omitted: both are opaque operator identifiers not tied to any persisted entity. The server may record an opaque identifier where a workflow calls for it — for example a `PlatformAdmin` id landing in a report's `reviewed_by` — but it never compares such an identifier to any entity's `id`.

`Anonymous` may only register new members. `Member` performs all giving, claiming, pickup coordination, wishlist, curb-alert, and reporting operations. `GroupModerator` inherits member capabilities and additionally moderates memberships and reports within groups they moderate. `PlatformAdmin` creates groups, overturns moderation actions, drives the logical clock, and shares the moderators' membership- and report-handling operations across all groups.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — members, groups, memberships, gift posts, claims, pickup plans, wishlists, curb alerts, reports, and moderation actions — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascades and recomputations.

`ReputationEvent` is the lone exception: as an append-only ledger entry it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock and the Epoch Sweep

The server maintains a single logical clock, and every time-based rule in this document — expiry, settlement, ageing, reinstatement, activation — is evaluated against it. Before any administrative intervention, the logical clock reads exactly `2026-05-01T00:00:00Z`; the server must never fall back to wall-clock time. A `PlatformAdmin` advances the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` instant, sets the server's logical time to it, and then runs the **epoch sweep**: a single atomic pass that resolves every time-driven transition whose moment has come.

The sweep's duties, all applied against the new logical now, are: expiring offers by moving claims from `OFFERED` to `EXPIRED` at their `offer_expires_at` (each triggering the vacancy cascade of §3.3); expiring posts from `OPEN` to `EXPIRED` at their `expires_at`; flipping curb alerts from `SCHEDULED` to `ACTIVE` at `starts_at` and from `ACTIVE` to `ENDED` at `ends_at`; settling reputation events whose age has reached seven days (`PENDING` to `SETTLED`); expiring strikes whose `active_until` has arrived (`ACTIVE` to `EXPIRED`, followed by the strike-point recomputation and any reinstatement it implies); reinstating suspended members whose `suspension_ends_at` has passed; and expiring wishlists whose `expires_at` has arrived. All side effects of the sweep are applied atomically within the clock-setting request.

### 2.6. Request Validation Order

When several checks could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and well-formed; failures yield `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted for the endpoint, and a `GroupModerator` additionally holds an `APPROVED` moderator membership in the target group; failures yield `ERR_UNAUTHORIZED`.
3. **Body schema** — required fields are present, types are valid, enum values are in range, email and datetime formats are valid, and unknown fields are rejected; failures yield `ERR_VALIDATION`.
4. **Existence** — every referenced resource exists, validated left to right: path identifiers first, then body foreign keys such as `group_id`, `post_id`, `claim_id`, and a report's `target_id` (interpreted according to `target_type`). Each missing resource surfaces its own not-found error, from `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`.
5. **Optimistic concurrency** — on the two versioned write endpoints, the expected version must match the entity's current `version`; a mismatch yields `ERR_STALE_VERSION`.
6. **State preconditions** — the target resource is in a state that permits the operation (for example a post must be `DRAFT` to publish, a claim `OFFERED` to accept); each violation surfaces its specific 409 state error.
7. **Member standing** — content-creating operations require the acting member's `status` to be `ACTIVE`; a suspended actor is rejected with `ERR_MEMBER_SUSPENDED`, a banned actor with `ERR_MEMBER_BANNED`.
8. **Relationship rules** — group membership, resource ownership, counterparty alternation, duplicate-claim and duplicate-membership uniqueness, self-claim prohibition, offer-target eligibility, and the negotiation round cap.
9. **Temporal rules** — interval well-formedness (`ERR_INVALID_TIME_RANGE`), porch-window overlap (`ERR_PICKUP_WINDOW_CONFLICT`), and curb-zone capacity (`ERR_CURB_ALERT_CAPACITY`).
10. **Capacity** — roster room remains before a membership is approved (`ERR_GROUP_FULL`).

Because authentication outranks existence, for instance, a request with bad headers against a nonexistent group fails with `ERR_UNAUTHENTICATED`, never with `ERR_GROUP_NOT_FOUND`; and because the concurrency check outranks the state checks, a stale version surfaces as `ERR_STALE_VERSION` even when the operation would also fail a state precondition.

### 2.7. Optimistic Concurrency Control

Two write endpoints carry optimistic concurrency protection, and only those two. Editing a gift post requires the non-optional request field `expected_gift_post_version`, carrying the client's last observed `version` of the post; if the post's current `version` has advanced beyond that value — through another edit or through any cascade that mutated the post — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). Updating a neighborhood group's policy likewise requires the non-optional `expected_group_version` field matching the group's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch, obliging the writer to re-read the group and resubmit against the fresh version. No other endpoint accepts a version field; all other mutations serialize through the state machine itself.

### 2.8. Reputation and Fairness Accounting

Reputation is computed from the `ReputationEvent` ledger, never stored as a mutable number. Each event carries `base_points` determined by its `event_type`: `WELCOME_BONUS` is worth 5 points, `GIFT_COMPLETED` 10, `RECEIVE_COMPLETED` 3, `NO_SHOW_PENALTY` negative 8, and `STRIKE_APPLIED` negative 2 per severity point of the strike that caused it. Every point value is **age-weighted**: an event's age in whole days is the floor of the elapsed seconds since its `created_at` divided by 86,400; events at most 30 days old weigh in full (factor 1.0), events 31 to 90 days old weigh three quarters (factor 0.75), and events older than 90 days weigh one half (factor 0.5). The evaluation order is pinned: each event's weighted points are first rounded half-up to exactly 1 decimal place, and only then summed. An empty event set sums to 0.0.

Two variants are exposed on every member read. The official `reputation_score` sums only `SETTLED` events; the provisional `pending_reputation_score` applies the identical formula over `PENDING` plus `SETTLED` events, so the two diverge whenever any event awaits settlement. Events settle — moving from `PENDING` to `SETTLED` with `settled_at` stamped — once their age reaches seven full days, during the epoch sweep.

A member's `fairness_score` is a separate integer between 0 and 100 that governs queue priority. It starts from a base of 50, gains 2 points per gift the member has completed within the trailing 90 whole days, loses 3 points per item received within the trailing 90 whole days, loses 10 points per active strike point, and gains a 5-point seniority bonus once the member's own account is at least 180 days old (measured in whole days from the member's `created_at`). The raw result is clamped: below 0 it becomes 0, above 100 it becomes 100. All arithmetic is integer arithmetic with no rounding.

### 2.9. Group Health and Report Service Levels

Each group carries a computed `health_score` that summarizes its recent civic performance: 2 points for every gift post in the group that reached `FULFILLED` within the trailing 30 whole days, minus 5 points for every report currently `OPEN` or `UNDER_REVIEW`, minus 10 points for every report resolved within the trailing 30 whole days whose `resolved_at` came after its `sla_due_at`. The score is an integer, recomputed after each report creation, each report resolution, each gift completion, and each clock sweep. The group's `health_tier` derives from the score: `GREEN` when the score is at least 20, `YELLOW` when it sits between 0 and 19 inclusive, and `RED` when it falls below 0.

The tier governs moderation responsiveness through a report's service-level deadline. A report's `sla_due_at` is computed exactly once, at the report's creation, from the tier in effect at that instant: 96 hours for a `GREEN` group, 72 hours for `YELLOW`, 48 hours for `RED`. It is never recomputed afterwards, even if the group's tier later changes; tier movements caused by resolving reports apply only to reports created afterwards. A resolution whose `resolved_at` exceeds `sla_due_at` counts as an overdue resolution in the health calculation above.

### 2.10. Strike Points, Suspension, and Ban Thresholds

Moderation strikes decay and accumulate under fixed thresholds. A strike remains active for 90 days from its creation (`active_until` is stamped at creation as `created_at` plus 90 days), after which the epoch sweep moves it to `EXPIRED` and it stops counting. A member's `active_strike_points` is the sum of `severity_points` over their moderation actions whose `action_type` is `STRIKE` and whose `status` is `ACTIVE`. The boundaries are pinned: at 3 or more points (3 exactly included) but fewer than 6, the member is suspended for 14 days; at 6 or more points, the member is banned. Suspension and ban are full cascades described in §3.8; the arithmetic here is plain integer points.

### 2.11. Interval Semantics and Time Buffers

Three interval regimes recur throughout the API and are pinned here once. Pickup windows are **closed intervals** guarded by a buffer: a proposed window conflicts with an existing confirmed window on the same porch when the new window's start falls before the existing window's end plus 15 minutes *and* the new window's end falls after the existing window's start minus 15 minutes — both comparisons strict, so a new window starting exactly at the existing end plus 15 minutes does not conflict. Curb-alert windows are **half-open intervals** — an alert occupies from its `starts_at` up to but not including its `ends_at` — and two such intervals overlap only when each starts before the other ends; two alerts that merely touch, one ending exactly when the other begins, do not overlap. Offer windows use a strict deadline: an offer is acceptable only while the logical now is strictly before the claim's `offer_expires_at`; at the exact instant of `offer_expires_at` the offer is already expired. All timestamp comparisons operate at one-second granularity. Trailing-window counts (the 90-day giving/receiving counts and the 30-day health inputs) are measured in whole days.

## 3. Business Logic & Workflows

### 3.1. Joining the Network: Members, Groups, and Rosters

Registration is the network's front door and the only door open to an `Anonymous` caller. A new member supplies an `email` — unique across the platform, compared case-insensitively — and a `display_name`. The account is born `ACTIVE`, and the system immediately records a `WELCOME_BONUS` reputation event worth 5 points in `PENDING` status, so newcomers begin with a small provisional standing that only becomes official after it settles. Reading a member returns, alongside the profile fields, the computed `reputation_score`, `pending_reputation_score`, `fairness_score`, `active_strike_points`, the trailing 90-day counters `given_count_90d` and `received_count_90d`, and — while suspended — the `suspension_ends_at` instant at which the sweep will reinstate them (null at all other times). A member's full reputation ledger is reachable as a filtered list of their events, with an optional `status` filter alongside the standard `limit` and `offset`.

Neighborhood groups are created exclusively by `PlatformAdmin`, each anchored by a `name` and a five-digit `zip_code`. Two policy knobs shape admission: `join_policy`, either `OPEN` or `APPROVAL_REQUIRED` (defaulting to `OPEN` when omitted), and `capacity`, the maximum number of approved members, which must lie between 2 and 10000 and defaults to 150. Group reads expose the computed roster fields — `member_count` (the number of memberships in `APPROVED` status) and `roster_status`, which reads `FULL` exactly when `member_count` has reached `capacity` and `ACCEPTING` otherwise — plus the health pair `health_score` and `health_tier`. A group's `name`, `join_policy`, and `capacity` may later be updated by a moderator of that group or a `PlatformAdmin` through the versioned policy update described in §2.7; such an update increments the group's `version` by one and recomputes `roster_status` whenever `capacity` changes.

A member joins by requesting a membership in a group, supplying the target `group_id`. Two guards precede admission: at most one membership per member–group pair may be live (`REQUESTED` or `APPROVED`) at a time — a second attempt is rejected with `ERR_MEMBERSHIP_EXISTS` — and the roster must have room. Under an `OPEN` join policy the request is auto-approved inline: the membership is created directly in `APPROVED` status, `member_count` increases by one, and `roster_status` is recomputed; should the roster already be full, the join is rejected with `ERR_GROUP_FULL`. Under `APPROVAL_REQUIRED` the membership is created in `REQUESTED` and awaits a decision. Approval by a moderator of that group (or a `PlatformAdmin`) requires the membership to still be `REQUESTED` — otherwise `ERR_MEMBERSHIP_NOT_REQUESTED` — and the roster to be `ACCEPTING`, since approving into a full roster fails with `ERR_GROUP_FULL`. Approval may optionally assign a `role`; when omitted the member joins as `MEMBER`, and assigning `MODERATOR` at approval time is how the first moderators of a group come to be. Rejection, also reserved to moderators and administrators, moves a `REQUESTED` membership to `REJECTED`. Memberships can be listed with `member_id`, `group_id`, `status`, and `role` filters.

Leaving and removal mirror each other. A member leaves their own `APPROVED` membership, moving it from `APPROVED` to `LEFT` — attempting to leave one not in `APPROVED` fails with `ERR_MEMBERSHIP_NOT_APPROVED` — and a moderator (or `PlatformAdmin`) removes a member under the same state rule, moving the membership from `APPROVED` to `REMOVED`. Either way the group loses one approved member: `member_count` decreases by one, `roster_status` is recomputed, and the departing member's claims **in that group** that are still `QUEUED` or `OFFERED` move to `WITHDRAWN`, each withdrawal running the vacancy cascade of §3.3 on the affected post. Moderation authority rides on this same mechanism: wherever this document says "a moderator of the group", it means the actor holds an `APPROVED` membership there with `role` equal to `MODERATOR`, and acting within a group context — moderating memberships, claiming, coordinating pickups, giver offers — presupposes an `APPROVED` membership, with `ERR_NOT_GROUP_MEMBER` (HTTP 403) greeting actors who lack one.

### 3.2. Offering an Item: The Gift Post Lifecycle

A giver composes a post inside a group: the payload names the `group_id`, a `title`, a `category` drawn from `FURNITURE`, `CLOTHING`, `FOOD`, `HOUSEHOLD`, `ELECTRONICS`, or `OTHER`, a `claim_mode` of `FIRST_COME`, `FAIRNESS_DRAW`, or `GIVER_PICK` (the queue policy of §3.3), an `expires_at` deadline that must lie strictly in the future at creation (`ERR_INVALID_TIME_RANGE` otherwise), and an optional `description` that defaults to an empty string. The post is born in `DRAFT`, invisible to claimants, with the creating member recorded as `giver_id`. While a post remains `DRAFT` or `OPEN` its author may edit the `title`, `description`, `category`, or `expires_at` through the versioned update of §2.7, each successful edit incrementing the post's `version` by one; posts past those states no longer accept edits.

Publishing moves the post from `DRAFT` to `OPEN` and is restricted to the giver (acting as anyone else earns `ERR_NOT_RESOURCE_OWNER`) whose account is in good standing; publishing a post that is not in `DRAFT` fails with `ERR_POST_NOT_DRAFT`. Publication is the moment wishlists come alive: every `ACTIVE` wishlist in the same group whose `keyword` appears as a case-insensitive substring of the post's `title`, and whose `category` is either unset or equal to the post's `category`, flips to `MATCHED` with `matched_post_id` pointing at the new post (§3.5).

An `OPEN` post ticks toward its deadline. When the logical clock reaches `expires_at` with the post still `OPEN`, the sweep moves it to `EXPIRED`, moves its `QUEUED` claims to `WITHDRAWN`, and releases any matched wishlists back to `ACTIVE` with `matched_post_id` cleared. A giver may also withdraw a post at will, moving it to `WITHDRAWN` — from `DRAFT` with no further consequence; from `OPEN`, with the same claim-withdrawal and wishlist-release side effects as expiry; and from `RESERVED`, provided no claim on the post has reached `ACCEPTED`. Withdrawing a `RESERVED` post moves both its `QUEUED` and `OFFERED` claims to `WITHDRAWN` and clears the post's `current_claim_id`. Withdrawal is forbidden once a claim stands `ACCEPTED` or the post has reached a terminal state, both rejected with `ERR_POST_NOT_WITHDRAWABLE`. A moderation action of type `CONTENT_REMOVAL` forces the same transition administratively (§3.7).

The post's head-slot mirror fields track the live offer. Whenever exactly one claim holds `OFFERED` status, the post sits in `RESERVED` with `current_claim_id` naming that claim and `current_offer_expires_at` mirroring the claim's own `offer_expires_at`; the holding claim can be dereferenced directly by id, or found by filtering the claim list with the `post_id` query parameter. When the head slot empties with nothing to promote, the post returns to `OPEN` and both mirror fields clear to null. This `OPEN` → `RESERVED` → `OPEN` cycle is the post's re-offer loop, and a post finally reaches `FULFILLED` only through a completed porch pickup. Posts can be browsed with `group_id`, `giver_id`, `status`, and `category` filters.

### 3.3. The Claim Queue: Modes, Promotion, and the Offer Window

Claiming an `OPEN` post creates the claim in `QUEUED` status — claiming a post in any other state fails with `ERR_POST_NOT_OPEN`. Three eligibility rules guard creation: the claimer must not be the post's own giver (`ERR_SELF_CLAIM`, HTTP 422); the same member may hold at most one live claim — `QUEUED`, `OFFERED`, or `ACCEPTED` — per post (`ERR_DUPLICATE_CLAIM`); and the claimer must be an approved member of the group per §3.1. Every claim receives a per-post monotonic `claim_seq` starting at 1, which serves as the final tie-break in queue ordering — after `created_at`, never the claim `id`. The creating member is recorded as `claimer_id`.

Promotion from `QUEUED` to `OFFERED` fires only when the post has no claim in `OFFERED` or `ACCEPTED` — the head slot is vacant — and follows the post's `claim_mode`. Under `FIRST_COME`, the queue is ordered by `created_at` ascending with `claim_seq` ascending as tie-break, a pure chronological order in which claimer attributes are ignored. Under `FAIRNESS_DRAW`, the queue is ordered by the claimer's `fairness_score` descending, then `created_at` ascending, then `claim_seq` ascending — fairness dominates chronology, so an identical queue can promote a different claimer than first-come would. Under `GIVER_PICK` there is no automatic promotion at all: the giver explicitly selects any `QUEUED` claim of the post, and attempting to offer a claim that is not `QUEUED` on that post fails with `ERR_CLAIM_NOT_QUEUED`. A brand-new claim on a vacant post under `FIRST_COME` or `FAIRNESS_DRAW` is promoted to `OFFERED` in the very same request that creates it.

Promotion stamps `offered_at` with the logical now and sets `offer_expires_at` exactly 24 hours later; simultaneously the post moves `OPEN` → `RESERVED` with its mirror fields set. The offered claimer may then accept — but only while the logical now is strictly before `offer_expires_at`, only on a claim still `OFFERED` (`ERR_CLAIM_NOT_OFFERED` otherwise, which also greets acceptances attempted after the sweep has already expired the offer), and only as themselves (`ERR_NOT_RESOURCE_OWNER`). Acceptance moves the claim from `OFFERED` to `ACCEPTED` and opens the pickup negotiation of §3.4. The claimer may instead decline, moving the claim from `OFFERED` to `DECLINED`. At the boundary instant itself the offer is already gone: when the clock reaches `offer_expires_at` the sweep moves the claim from `OFFERED` to `EXPIRED`.

Every departure from the head slot runs the **vacancy cascade**. Whether the head claim moved to `DECLINED` by its claimer's choice, to `EXPIRED` by the sweep, to `WITHDRAWN` voluntarily or in bulk by a member-level sanction, or to `NO_SHOW` after a missed pickup, the post's queue is re-evaluated: under `FIRST_COME` or `FAIRNESS_DRAW` the rank-1 `QUEUED` claim is promoted to `OFFERED` and the post stays `RESERVED` with refreshed mirrors; under `GIVER_PICK`, or when no `QUEUED` claim remains, nobody is promoted and the post falls back `RESERVED` → `OPEN` with `current_claim_id` and `current_offer_expires_at` cleared. A claimer may also voluntarily withdraw a claim while it is `QUEUED` or `OFFERED`, moving it to `WITHDRAWN`; withdrawing from any other state fails with `ERR_CLAIM_NOT_WITHDRAWABLE`. Withdrawing a `QUEUED` claim simply removes it from the line; withdrawing the `OFFERED` head runs the same vacancy cascade as a decline. Claims can be listed filtered by `post_id`, `claimer_id`, or `status`.

### 3.4. Porch-Pickup Negotiation and the Handoff

Once a claim stands `ACCEPTED`, the two parties arrange the handoff through a pickup plan. Either the giver or the claimer may open the negotiation by proposing a plan against the claim — supplying the `claim_id`, a `window_start`, and a `window_end` that must be strictly later (`ERR_INVALID_TIME_RANGE` when the end does not exceed the start), plus an optional `location_note` for porch instructions that defaults to an empty string. Creating a plan on a claim that is not `ACCEPTED` fails with `ERR_CLAIM_NOT_ACCEPTED`. The plan is born `PROPOSED` with `round_number` 1, the creator recorded as both `proposer_id` and `last_proposer_id`.

Negotiation is a bounded, alternating protocol. A counter-proposal replaces `window_start`, `window_end`, and optionally `location_note`, moves the plan from `PROPOSED` to `COUNTERED` (or keeps it in `COUNTERED`), increments `round_number` by one, and records the actor as the new `last_proposer_id`. The alternation is strict: the actor must be the giver or the claimer of the underlying claim and must not be the member who made the most recent proposal — violations surface `ERR_NOT_COUNTERPARTY` (HTTP 403), which also greets non-parties. The loop is capped at three rounds: a counter attempted when `round_number` has already reached 3 is rejected with `ERR_MAX_NEGOTIATION_ROUNDS` (HTTP 422). Countering or confirming a plan that has left the negotiable states — anything other than `PROPOSED` or `COUNTERED` — fails with `ERR_PICKUP_NOT_NEGOTIABLE`. Confirmation mirrors countering in its actors: the party who did **not** make the latest proposal confirms it, moving the plan from `PROPOSED` or `COUNTERED` to `CONFIRMED`. Either party may abandon a negotiable plan by cancelling it into `CANCELLED`.

Every window that could become a commitment — at creation, at each counter, and again at confirm — must pass the **giver's porch overlap rule** of §2.11: the competing set is the giver's other `CONFIRMED` plans (plans that are merely `PROPOSED` or `COUNTERED`, or already `COMPLETED`, `MISSED`, or `CANCELLED`, never block), and a collision under the 15-minute double-sided buffer is rejected with `ERR_PICKUP_WINDOW_CONFLICT`.

The giver alone closes out a confirmed plan, and only while it is `CONFIRMED` (`ERR_PICKUP_NOT_CONFIRMED` otherwise). Marking the pickup complete moves the plan to `COMPLETED` and the claim from `ACCEPTED` to `FULFILLED`, which in turn moves the post to `FULFILLED` and fires the fulfillment cascade: a `GIFT_COMPLETED` reputation event worth 10 points in `PENDING` for the giver, a `RECEIVE_COMPLETED` event worth 3 points in `PENDING` for the claimer, a wishlist fulfillment sweep for the claimer (§3.5), recomputation of the giver's `given_count_90d` and the claimer's `received_count_90d`, and a refresh of the group's `health_score` as one more completed gift enters the 30-day window. If instead the window passes with no handoff, the giver reports a no-show — but only after the logical now has passed `window_end` (`ERR_PICKUP_WINDOW_NOT_PASSED` before then) — which moves the plan to `MISSED` and the claim from `ACCEPTED` to `NO_SHOW`, stamps a `NO_SHOW_PENALTY` event of negative 8 points in `PENDING` on the claimer, and returns the item to the queue through the same vacancy cascade a decline would have triggered. Plans can be browsed by `claim_id`, `proposer_id`, or `status`.

### 3.5. Wishlists: Matching, Rematching, and Fulfillment

A wishlist entry lets a member register demand ahead of supply. Creating one takes the `group_id` that scopes the wish and a `keyword`; an optional `category` narrows matching to one of the six item categories, while leaving it unset matches any category. The wishing member is recorded as `member_id`, and the entry is born `ACTIVE` with an `expires_at` set exactly 30 days after creation.

Matching is a publish-time event: as §3.2 describes, when a post in the same group is published and the wishlist's `keyword` is a case-insensitive substring of its `title` with the category rule satisfied, the wishlist moves from `ACTIVE` to `MATCHED` and its `matched_post_id` records the post. The bond is fragile by design — if the matched post is later withdrawn or expires, the wishlist drops back from `MATCHED` to `ACTIVE` and `matched_post_id` clears, resuming the wait for the next matching post. This `ACTIVE` → `MATCHED` → `ACTIVE` rematch cycle can repeat any number of times within the entry's 30-day life.

Fulfillment arrives through the claim pipeline. When a claim by the wishlist's own member in the same group reaches `FULFILLED` on a post whose title and category satisfy the entry's keyword and category rules, the wishlist — whether still `ACTIVE` or already `MATCHED` — moves to `FULFILLED`. A member may also cancel their own entry while it is `ACTIVE` or `MATCHED`, moving it to `CANCELLED`; attempting to cancel an entry already in a terminal state fails with `ERR_WISHLIST_NOT_ACTIVE`. Finally, when the logical clock reaches the entry's `expires_at`, the sweep moves it from `ACTIVE` or `MATCHED` to `EXPIRED`, clearing `matched_post_id` in the matched case. Wishlists can be listed with `member_id`, `group_id`, `matched_post_id`, and `status` filters.

### 3.6. Curb Alerts and Zone Capacity

Curb alerts announce time-boxed curbside giveaways — the free-cycle "everything on the lawn until Sunday" pattern. A member creates one with the `group_id`, a free-form `zone` label naming the block or area, a `starts_at`, and an `ends_at` that must be strictly later (`ERR_INVALID_TIME_RANGE` otherwise); the creator is recorded as `creator_id` and the alert is born `SCHEDULED`.

Zone capacity protects neighborhoods from alert pile-ups. Because alerts occupy half-open intervals (§2.11), two alerts in the same `(group_id, zone)` overlap only when each starts before the other ends, and merely adjacent alerts do not overlap at all. Creation is rejected with `ERR_CURB_ALERT_CAPACITY` (HTTP 409) whenever the new interval would overlap three or more existing `SCHEDULED` or `ACTIVE` alerts in the same group and zone — that is, at most three mutually overlapping live alerts are permitted per zone, and it is the fourth overlapping one that fails.

The epoch sweep animates the lifecycle: an alert flips from `SCHEDULED` to `ACTIVE` when the logical now reaches `starts_at`, and from `ACTIVE` to `ENDED` when it reaches `ends_at`. Before it ends, the alert may be cancelled into `CANCELLED` either by its creator or by a moderator of the group; cancelling an alert already `ENDED` or `CANCELLED` fails with `ERR_CURB_ALERT_NOT_CANCELLABLE`. Alerts can be browsed with `group_id`, `creator_id`, `zone`, and `status` filters.

### 3.7. Reporting, Review, and Moderation Actions

Any member may file a report inside a group, supplying the `group_id`, a `target_type` of `MEMBER`, `GIFT_POST`, `CLAIM`, or `CURB_ALERT`, the `target_id` of the specific target — interpreted according to `target_type` and validated for existence against the matching collection, so a missing gift-post target surfaces `ERR_GIFT_POST_NOT_FOUND`, a missing claim target `ERR_CLAIM_NOT_FOUND`, and a missing curb-alert target `ERR_CURB_ALERT_NOT_FOUND` — a `category` of `NO_SHOW`, `SAFETY`, `SPAM`, `PROHIBITED_ITEM`, `HARASSMENT`, or `OTHER`, and optional free-text `details` defaulting to an empty string. The filing member is recorded as `reporter_id`. The report is born `OPEN`, its `sla_due_at` is stamped once from the group's `health_tier` in effect at that instant per §2.9, and the group's `health_score` is immediately recomputed to reflect one more open report. Reading a single report is restricted to its reporter, moderators of the group, and `PlatformAdmin`; the report list — filterable by `group_id`, `reporter_id`, and `status` — is visible to moderators and administrators only.

Review begins when a moderator of the report's group (or a `PlatformAdmin`) starts review, moving the report from `OPEN` to `UNDER_REVIEW` and stamping `reviewed_by` with the actor — a member id for a moderator, the opaque operator id for an administrator; a report not in `OPEN` rejects the attempt with `ERR_REPORT_NOT_OPEN`. Resolution then takes one of two shapes, expressed through the `resolution` field, and any resolve attempted on a report not `UNDER_REVIEW` fails with `ERR_REPORT_NOT_UNDER_REVIEW`. Resolving with `DISMISS` moves the report to `RESOLVED_DISMISSED` with no further action. Resolving with `ACTION` moves the report to `RESOLVED_ACTION` and requires an `action_type` — `WARNING`, `STRIKE`, or `CONTENT_REMOVAL` — and creates a `ModerationAction` whose `member_id` subject is derived from the report target: the target itself for a `MEMBER` report, the post's `giver_id` for a `GIFT_POST` report, the claim's `claimer_id` for a `CLAIM` report, and the alert's `creator_id` for a `CURB_ALERT` report. A `STRIKE` action requires `severity_points` between 1 and 3 (required exactly when the action type is `STRIKE`); `CONTENT_REMOVAL` is valid only when the report's `target_type` is `GIFT_POST`; an optional `rationale` defaults to an empty string. Every moderation action is born `ACTIVE` with `active_until` stamped 90 days out, its `report_id` pointing back to the resolving report. Either resolution stamps `resolved_at` and recomputes the group's health — one fewer open report, and an overdue-resolution penalty if `resolved_at` has passed `sla_due_at`.

An `ACTION` resolution's consequences depend on the action type. A `WARNING` is recorded without further cascade. A `STRIKE` immediately records a `STRIKE_APPLIED` reputation event on the subject — negative 2 points per severity point, in `PENDING` — and recomputes the subject's `active_strike_points`, which may fire the sanction cascade of §3.8. A `CONTENT_REMOVAL` forcibly moves the target post to `WITHDRAWN` under its withdrawal side effects, live claims and matched wishlists included.

Moderation actions can be inspected individually or listed with `report_id`, `member_id`, and `status` filters. Two forces can retire an action. The epoch sweep moves an action from `ACTIVE` to `EXPIRED` when the logical now reaches its `active_until`; the subject's strike points are then recomputed, and a suspended subject whose points have dropped below 3 is reinstated. A `PlatformAdmin` may instead overturn an `ACTIVE` action into `OVERTURNED` — attempting to overturn one in any other state fails with `ERR_ACTION_NOT_OVERTURNABLE` — after which the subject's points are recomputed: a suspended subject falling below 3 points returns to `ACTIVE` with `suspension_ends_at` cleared, and a banned subject falling below 6 points is restored to `SUSPENDED` when 3 or more points remain or directly to `ACTIVE` when fewer than 3 remain.

### 3.8. Reputation Events and the Sanction Cascade

The reputation ledger, introduced in §2.8, is fed by five event types across the workflows above: `WELCOME_BONUS` at registration, `GIFT_COMPLETED` and `RECEIVE_COMPLETED` at pickup completion, `NO_SHOW_PENALTY` at a reported no-show, and `STRIKE_APPLIED` at a strike resolution. Every event is born `PENDING` and settles during the epoch sweep once its age reaches seven full days, moving to `SETTLED` with `settled_at` stamped; only then does it enter the official `reputation_score`. Individual events are readable by id, and a member's ledger is listable with a `status` filter.

Strikes escalate through the member lifecycle. While a member's `active_strike_points` stay below 3 nothing happens. When a strike application, an overturn, or the sweep's strike-expiry recomputation leaves the total at 3 or more but fewer than 6 — the boundary at exactly 3 included — the member moves from `ACTIVE` to `SUSPENDED`, `suspension_ends_at` is set 14 days out, and the suspension cascade fires: every claim the member holds in `QUEUED` or `OFFERED` status moves to `WITHDRAWN`, and each `OFFERED` withdrawal runs the vacancy cascade on its post, promoting the next `QUEUED` claim per the post's `claim_mode` or returning the post from `RESERVED` to `OPEN` when nothing can be promoted. When the total reaches 6 or more, the member moves to `BANNED` — from `ACTIVE` or, if already suspended, from `SUSPENDED` under the same cascade — every one of their `REQUESTED` or `APPROVED` memberships becomes `REMOVED` with each owning group's `member_count` and `roster_status` recomputed, and their live claims move to `WITHDRAWN` with the same vacancy cascade as a suspension. `BANNED` is terminal through ordinary operation; only an administrator's strike overturn can walk a banned member back per §3.7.

Reinstatement runs through two doors. The epoch sweep returns a `SUSPENDED` member to `ACTIVE` once the logical now reaches `suspension_ends_at`, clearing the field to null. An overturn or strike expiry that drops the total below 3 reinstates the member on the spot by the same path. In both cases the door closes behind them: claims and memberships withdrawn by the cascade are not restored. And while sanctions stand, the member standing rule of §2.6 bites — a `SUSPENDED` member attempting any content-creating operation (joining groups, posting gifts, claiming, proposing pickups, wishing, posting curb alerts, filing reports) is rejected with `ERR_MEMBER_SUSPENDED`, and a `BANNED` member with `ERR_MEMBER_BANNED`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/v1` prefix. Operations that create a new resource return `201 Created`; operations that read, modify, or drive a transition on an existing resource return `200 OK`. The table below summarizes the HTTP contract only — request payloads, side effects, and preconditions are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/members` | Register a member; creates a WELCOME_BONUS reputation event | Anonymous |
| GET | `/v1/members/{id}` | Read a member incl. computed reputation/fairness/strike fields | Member, GroupModerator, PlatformAdmin |
| GET | `/v1/members/{id}/reputation-events` | List reputation events of a member | Member, GroupModerator, PlatformAdmin |
| POST | `/v1/groups` | Create a neighborhood geo-group | PlatformAdmin |
| GET | `/v1/groups/{id}` | Read a group incl. roster and health fields | Member, GroupModerator, PlatformAdmin |
| PUT | `/v1/groups/{id}` | Update group policy (OCC on group version) | GroupModerator, PlatformAdmin |
| POST | `/v1/memberships` | Request to join a group; OPEN policy auto-approves inline | Member |
| GET | `/v1/memberships/{id}` | Read a membership | Member, GroupModerator, PlatformAdmin |
| GET | `/v1/memberships` | Filtered list of memberships | Member, GroupModerator, PlatformAdmin |
| POST | `/v1/memberships/{id}/approve` | Approve a REQUESTED membership; optional role assignment | GroupModerator, PlatformAdmin |
| POST | `/v1/memberships/{id}/reject` | Reject a REQUESTED membership | GroupModerator, PlatformAdmin |
| POST | `/v1/memberships/{id}/leave` | Member leaves a group | Member |
| POST | `/v1/memberships/{id}/remove` | Moderator removes a member from the group | GroupModerator, PlatformAdmin |
| POST | `/v1/gift-posts` | Create a gift post in DRAFT | Member |
| GET | `/v1/gift-posts/{id}` | Read a gift post | Member, GroupModerator, PlatformAdmin |
| GET | `/v1/gift-posts` | Filtered list of gift posts | Member, GroupModerator, PlatformAdmin |
| PUT | `/v1/gift-posts/{id}` | Edit a DRAFT/OPEN post (OCC on post version) | Member |
| POST | `/v1/gift-posts/{id}/publish` | Publish DRAFT → OPEN; triggers the wishlist match sweep | Member |
| POST | `/v1/gift-posts/{id}/withdraw` | Withdraw a post (blocked while a claim is ACCEPTED) | Member |
| POST | `/v1/gift-posts/{id}/offer` | GIVER_PICK: giver offers the item to a specific QUEUED claim | Member |
| POST | `/v1/claims` | Claim an OPEN post; auto-promotes when the head slot is vacant | Member |
| GET | `/v1/claims/{id}` | Read a claim | Member, GroupModerator, PlatformAdmin |
| GET | `/v1/claims` | Filtered list of claims | Member, GroupModerator, PlatformAdmin |
| POST | `/v1/claims/{id}/accept` | Claimer accepts a live offer | Member |
| POST | `/v1/claims/{id}/decline` | Claimer declines an offer; triggers the vacancy cascade | Member |
| POST | `/v1/claims/{id}/withdraw` | Claimer withdraws a QUEUED/OFFERED claim | Member |
| POST | `/v1/pickup-plans` | Propose a porch-pickup window for an ACCEPTED claim | Member |
| GET | `/v1/pickup-plans/{id}` | Read a pickup plan | Member, GroupModerator, PlatformAdmin |
| GET | `/v1/pickup-plans` | Filtered list of pickup plans | Member, GroupModerator, PlatformAdmin |
| POST | `/v1/pickup-plans/{id}/counter` | Counter-propose a new window (max 3 rounds, alternating parties) | Member |
| POST | `/v1/pickup-plans/{id}/confirm` | Confirm the latest proposal (by the other party) | Member |
| POST | `/v1/pickup-plans/{id}/cancel` | Cancel a negotiable plan | Member |
| POST | `/v1/pickup-plans/{id}/complete` | Giver confirms the porch pickup happened | Member |
| POST | `/v1/pickup-plans/{id}/miss` | Giver reports a no-show after the window has passed | Member |
| POST | `/v1/wishlists` | Create a wishlist entry (30-day lifetime) | Member |
| GET | `/v1/wishlists/{id}` | Read a wishlist | Member, GroupModerator, PlatformAdmin |
| GET | `/v1/wishlists` | Filtered list of wishlists | Member, GroupModerator, PlatformAdmin |
| POST | `/v1/wishlists/{id}/cancel` | Cancel an ACTIVE/MATCHED wishlist | Member |
| POST | `/v1/curb-alerts` | Create a curb-alert window (zone overlap capacity 3) | Member |
| GET | `/v1/curb-alerts/{id}` | Read a curb alert | Member, GroupModerator, PlatformAdmin |
| GET | `/v1/curb-alerts` | Filtered list of curb alerts | Member, GroupModerator, PlatformAdmin |
| POST | `/v1/curb-alerts/{id}/cancel` | Cancel a SCHEDULED/ACTIVE curb alert | Member, GroupModerator |
| POST | `/v1/reports` | File a moderation report; SLA keyed on group health tier at creation | Member |
| GET | `/v1/reports/{id}` | Read a report (reporter, group moderator, or admin) | Member, GroupModerator, PlatformAdmin |
| GET | `/v1/reports` | Filtered list of reports | GroupModerator, PlatformAdmin |
| POST | `/v1/reports/{id}/start-review` | Move a report OPEN → UNDER_REVIEW | GroupModerator, PlatformAdmin |
| POST | `/v1/reports/{id}/resolve` | Resolve with DISMISS or ACTION (WARNING / STRIKE / CONTENT_REMOVAL) | GroupModerator, PlatformAdmin |
| GET | `/v1/moderation-actions/{id}` | Read a moderation action | Member, GroupModerator, PlatformAdmin |
| GET | `/v1/moderation-actions` | Filtered list of moderation actions | Member, GroupModerator, PlatformAdmin |
| POST | `/v1/moderation-actions/{id}/overturn` | Overturn an ACTIVE action; may reinstate the member | PlatformAdmin |
| GET | `/v1/reputation-events/{id}` | Read a reputation event | Member, GroupModerator, PlatformAdmin |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock and run the epoch sweep | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_GIFT_POST_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_PICKUP_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_WISHLIST_NOT_FOUND` | 404 Not Found |
| `ERR_CURB_ALERT_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_MODERATION_ACTION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MEMBER_SUSPENDED` | 403 Forbidden |
| `ERR_MEMBER_BANNED` | 403 Forbidden |
| `ERR_NOT_GROUP_MEMBER` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_COUNTERPARTY` | 403 Forbidden |
| `ERR_MEMBERSHIP_EXISTS` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_REQUESTED` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_APPROVED` | 409 Conflict |
| `ERR_GROUP_FULL` | 409 Conflict |
| `ERR_POST_NOT_DRAFT` | 409 Conflict |
| `ERR_POST_NOT_OPEN` | 409 Conflict |
| `ERR_POST_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_OFFERED` | 409 Conflict |
| `ERR_CLAIM_NOT_ACCEPTED` | 409 Conflict |
| `ERR_CLAIM_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_QUEUED` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM` | 409 Conflict |
| `ERR_SELF_CLAIM` | 422 Unprocessable Content |
| `ERR_PICKUP_NOT_NEGOTIABLE` | 409 Conflict |
| `ERR_PICKUP_NOT_CONFIRMED` | 409 Conflict |
| `ERR_PICKUP_WINDOW_NOT_PASSED` | 409 Conflict |
| `ERR_PICKUP_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_MAX_NEGOTIATION_ROUNDS` | 422 Unprocessable Content |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Content |
| `ERR_CURB_ALERT_CAPACITY` | 409 Conflict |
| `ERR_CURB_ALERT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_WISHLIST_NOT_ACTIVE` | 409 Conflict |
| `ERR_REPORT_NOT_OPEN` | 409 Conflict |
| `ERR_REPORT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_ACTION_NOT_OVERTURNABLE` | 409 Conflict |
