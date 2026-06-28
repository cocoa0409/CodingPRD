# Matchmaking & Dating Service API — Product Requirements Document

## 1. Introduction

Modern matchmaking is a high-touch, relationship-driven business: prospects are screened by hand, paired through human judgement augmented by compatibility scoring, and held to a contractual promise of a certain number of curated introductions over the life of a membership. This document specifies the backend API that operationalizes that promise. The service tracks a member from first contact as an unscreened prospect, through identity and questionnaire screening, into an active paid membership whose central commitment is a *matches guarantee* — a finite pool of introduction credits the member is entitled to over a committed term.

The platform must reconcile several competing concerns at once. An introduction is a two-party negotiation: it only becomes actionable when **both** members accept, and either party can decline at any point. Each suggested introduction draws down the suggesting member's guarantee pool, and that pool must be defended against double-spending, refunded when introductions collapse, and reported in two distinct flavors — what has been irrevocably committed versus what is provisionally forecast. Members may pause their membership through freeze windows that extend the term, book coaching sessions subject to a no-show discipline, order an optional background check, and ultimately succeed (and exit) or churn. Because freezes, expiry, and strike decay all turn on the passage of time, the system runs on a controllable logical clock rather than wall-clock time, so that operators and tests can deterministically advance time.

This API is consumed by four operator and member personas working in concert, and every monetary, calendar, and guarantee computation must be exactly reproducible. The sections below define the global contract first, then the business workflows where the detailed rules live, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `BillingAdmin`, `ScreeningOfficer`, `Matchmaker`, and `Member`.

Three of these roles are **operator** roles whose identity is opaque. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same is true when `X-User-Role` is `ScreeningOfficer` and when `X-User-Role` is `Matchmaker`: in each case `X-User-ID` is an opaque operator identifier, recorded where useful (for example, the `coach_user_id` captured on a coaching session is the opaque Matchmaker operator who runs it) but never matched against any entity's `id`.

The `Member` role is entity-backed. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's owning-member foreign key to `X-User-ID`. A `Member` may act only on their own introductions, feedback, preferences, dates, coaching sessions, and background checks; acting on a resource owned by a different member is an `ERR_FORBIDDEN`. The owning-member foreign key is exposed as `member_id` on a member's screenings, preferences, memberships, coaching sessions, and background checks, and ownership is decided by comparing that `member_id` to `X-User-ID`. For introduction-scoped actions a member is considered an owner when their `id` is one of the two parties to the introduction.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list-based response carries the following fields inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Each persisted resource is assigned an `id`: a server-minted UUID with no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, stamped at creation.

Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every mutation, and a `version` integer that begins at 1 and increases by exactly one on every mutation, including mutations applied by cascades. The `Member` and `Introduction` entities expose a `version` that is the basis for optimistic concurrency control (see §2.10). All entities in this system — `MembershipPlan`, `Member`, `Screening`, `Preference`, `Membership`, `Freeze`, `Introduction`, `Feedback`, `DateEvent`, `CoachingSession`, and `BackgroundCheck` — carry the full set of common properties (`id`, `created_at`, `updated_at`, `version`).

### 2.5. The Logical Clock

The service never reads wall-clock time. Instead it maintains a single server-wide logical clock. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it holds that default rather than falling back to the host's real time. An administrative test-driving capability sets the clock to an arbitrary instant supplied as `to_iso8601`; the response reports the resulting `now`. All time-dependent rules — freeze activation, membership expiry, date and session start gating, age-gap eligibility, refund proration, and no-show strike decay — read this clock.

Advancing the clock does not eagerly sweep the database. Instead, time-driven transitions are evaluated **lazily**: the next operation that touches an affected resource reconciles it. Specifically, a `SCHEDULED` freeze whose start instant has arrived flips to `ACTIVE`, an `ACTIVE` membership past its term end with the guarantee unmet flips to `EXPIRED`, and a member's no-show strike count is recomputed for decay, all on the next read or operation that touches the relevant record.

### 2.6. Hierarchical Consistency and Cascades

When an operation changes a resource, the change is recorded on that resource by refreshing its `updated_at` and incrementing its `version`. Several operations in this system fan out across multiple entities, and each entity touched by such a fan-out independently has its own `updated_at` refreshed and its own `version` incremented.

The deepest cascade is member exit, which propagates three levels deep: exiting a member closes that member's open introductions, and closing an introduction in turn cancels any scheduled date on it. Declining or closing an introduction below the mutual stage refunds the guarantee credits it had drawn; reaching the mutual stage commits those credits, after which closing the introduction refunds nothing. A completed freeze extends the term and bumps the member. A background check that comes back flagged closes the subject's open introductions. The precise mechanics of every cascade live in the §3 workflow that owns the triggering action; this subsection establishes only that each affected entity is independently re-stamped and re-versioned.

### 2.7. Nested Resource Retrieval and Path Validation

Many endpoints address nested resources through multiple path identifiers. The system validates these identifiers strictly left-to-right and rejects the request at the **first** identifier that does not resolve to an existing resource, returning that identifier's specific 404 error before evaluating anything further to its right. For a path that names a member and then a membership, screening, or check beneath it, the member is validated first (`ERR_MEMBER_NOT_FOUND`), then the nested resource. The 404 errors are resource-specific: `ERR_MEMBER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_INTRODUCTION_NOT_FOUND`, `ERR_FREEZE_NOT_FOUND`, `ERR_DATE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, and `ERR_CHECK_NOT_FOUND`.

### 2.8. Validation Ordering

When several validation classes could fire on a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) authorization of the role and ownership (`ERR_FORBIDDEN`); (3) existence of every path resource, left-to-right (the 404 family above); (4) request-body well-formedness — required fields present, enum values legal, and numeric ranges respected, such as a rating between 1 and 5 inclusive, a partner minimum age of at least 18, a maximum age not less than the minimum age, and an end instant strictly after a start instant — failing with `ERR_INVALID_REQUEST`; (5) the state of the acting or target resource (the 409 state family); (6) cross-entity referential integrity (`ERR_NOT_INTRODUCTION_PARTY`, `ERR_SELF_INTRODUCTION`, `ERR_PLAN_ARCHIVED`); (7) suggestion eligibility and safety gates (`ERR_MEMBER_NOT_ELIGIBLE`, `ERR_PREFERENCE_MISMATCH`, `ERR_DEALBREAKER`, `ERR_BACKGROUND_FLAGGED`); (8) calendar overlap and buffer checks (`ERR_DATE_OVERLAP`, `ERR_COACHING_BUFFER_CONFLICT`); (9) the compatibility threshold (`ERR_COMPATIBILITY_TOO_LOW`); (10) coaching availability (`ERR_COACHING_SUSPENDED`); (11) the guarantee pool sufficiency (`ERR_GUARANTEE_EXHAUSTED`); and finally (12) the optimistic-concurrency version check (`ERR_STALE_VERSION`). Where a single endpoint is guarded by several of these classes — introduction suggestion is the densest example, guarded by classes 6 through 12 — an earlier class always masks a later one.

### 2.9. Monetary Precision and Rounding

All money in this system is expressed in integer cents. Where a calculation produces a fractional cent — notably the per-session coaching refund rate — the value is rounded using the round-half-up convention, and the precise point in the computation at which rounding is applied is part of the specification and is pinned per calculation in §3 (see the refund rules). Compatibility scores, by contrast, are real numbers carried to exactly two decimal places, also using round-half-up.

### 2.10. Optimistic Concurrency Control

Two write operations defend a parent entity against acting on a stale view of it, and each requires the client to pass the parent's last-observed `version` as a mandatory field.

The first is introduction suggestion. A suggestion request must carry `expected_member_a_version` equal to the current `version` of the suggesting member (member A). Because suggesting an introduction consumes guarantee credits from member A's record, a client that has not seen the most recent state of that record could overdraw the pool; if member A's `version` has advanced since the caller last read it — for instance because another suggestion already consumed credits — the request is rejected with `ERR_STALE_VERSION` and HTTP status 412.

The second is responding to an introduction. A response request must carry `expected_introduction_version` equal to the current `version` of the target introduction. Because responding can commit or refund credits as the introduction crosses to the mutual or declined stage, a client acting on an introduction whose `version` has already advanced — because the counterpart's response was recorded first — is rejected with `ERR_STALE_VERSION` and HTTP status 412 rather than re-applying its response to a changed record.

These two endpoints are the only ones that take a version field. Every other write operation processes without an OCC check.

### 2.11. The Matches Guarantee and Credit Accounting

The commercial heart of a membership is the **matches guarantee**: a finite count of introduction credits the member is entitled to over the term. The guarantee pool is reported in two distinct flavors that diverge whenever introductions are still in flight, and both are surfaced as computed fields on the member. The **committed** remaining figure counts against the guarantee only those introductions that have actually reached the mutual stage (or were closed after having been mutual), and is used to decide whether the membership obligation has been met. The **forecast** remaining figure additionally treats every still-open suggested or one-sided introduction as provisionally consuming the pool, and is the figure that gates whether a new suggestion may proceed. Both are floored at zero, and both exclude introductions that declined or were closed below the mutual stage, because those introductions' credits were refunded. The exact arithmetic of each, and of credit consumption and refund, lives in §3.4 and §3.5.

## 3. Business Logic & Workflows

### 3.1. Plans and the Membership Catalogue

A `BillingAdmin` curates the catalogue of `MembershipPlan` records, each created with a `tier` of `BASIC`, `PLUS`, or `ELITE` (a tier is unique among non-archived plans), a `monthly_fee_cents` of at least zero, a `term_months` of at least one, a `guaranteed_introductions` count of at least zero (the matches-guarantee size), an `included_coaching_sessions` count of at least zero, a `coaching_value_cents` total of at least zero (the bundled coaching value that becomes the per-session refund basis), and a `background_check_addon_cents` one-time price of at least zero for the optional add-on. A plan may also set `priority_match_enabled`; when omitted this flag defaults to `false`. When `priority_match_enabled` is `true`, every introduction created under a membership on this plan consumes two guarantee credits instead of one (priority matching). On creation a plan's `status` is `ACTIVE` and its `archived` flag is `false`.

A plan may be archived. Archiving sets `archived` to `true` and flips `status` to `ARCHIVED`; an archived plan rejects new memberships but leaves existing memberships untouched. Listing plans excludes archived plans unless the caller passes `include_archived` set to true. Every operator role and the member role may read plans and an individual plan; the reverse lookup that lists the memberships purchased on a plan is available to the three operator roles.

### 3.2. From Prospect to Active Member: Screening and Activation

A new person enters the funnel when a `ScreeningOfficer` or `Matchmaker` registers them, supplying `email`, `full_name`, `birth_date` (the date of birth in ISO 8601 UTC, later used for age-gap eligibility against the clock), `city` (the home-city label used by location proximity scoring), and `gender` of `MALE`, `FEMALE`, or `NONBINARY`. The email must be unique among members whose status is not `EXITED`. The new member starts in status `PROSPECT`, with `screening_decision` of `NONE` and `version` 1.

A `ScreeningOfficer` opens a screening for a prospect by supplying a `questionnaire_score` between 0 and 100 inclusive and the boolean `identity_verified` indicating whether government ID was verified at intake. Opening a screening is permitted only while the member is in `PROSPECT`; otherwise the request is rejected with `ERR_MEMBER_NOT_PROSPECT`. The act transitions the member from `PROSPECT` to `SCREENING` and creates a `Screening` whose `decision` and `status` both begin at `PENDING`.

The `ScreeningOfficer` then decides the screening, supplying a `decision` of `APPROVED` or `REJECTED` and an optional free-text `decision_note` (which defaults to an empty string) recorded at decision time. Deciding is allowed only while the screening's `decision` is still `PENDING`; a second decision attempt is rejected with `ERR_SCREENING_ALREADY_DECIDED`. The two outcomes are symmetric in form and must be specified with equal care:

- On `APPROVED`, the screening's `decision` and mirrored `status` both become `APPROVED`, and the member's `screening_decision` becomes `APPROVED`. Approval alone does **not** flip the member to `ACTIVE`; a member with an approved screening but no membership remains in `SCREENING`. The flip to `ACTIVE` happens only when a membership is subsequently activated.
- On `REJECTED`, the screening's `decision` and mirrored `status` both become `REJECTED`, the member's `screening_decision` becomes `REJECTED`, and the member's status moves directly to `EXITED`, because rejected applicants leave the funnel.

Membership activation is a `BillingAdmin` action that names the `plan_id` to purchase. Activation requires the member's `screening_decision` to be `APPROVED`; otherwise it is rejected with `ERR_MEMBER_NOT_APPROVED`. The named plan must not be archived; activation against an archived plan is rejected with `ERR_PLAN_ARCHIVED`. On success a `Membership` is created: its `start_at` is stamped from the logical clock, its `guaranteed_introductions` is snapshotted from the plan's `guaranteed_introductions` at this moment (later edits to the plan never change this pinned snapshot), its `base_term_end_at` is computed as the start instant plus the plan's `term_months` whole calendar months before any freeze extension, and its `status` becomes `ACTIVE`. Activation flips the member's status from `SCREENING` to `ACTIVE`, sets the member's `active_membership_id` back-pointer to the new membership's `id`, computes the member's `term_end_at`, and increments the member's `version` by one. A member's `active_membership_id` is null when there is no active membership and is otherwise discoverable through the member's membership list. The membership also exposes a computed `credits_consumed_committed` (the sum of guarantee credits consumed by introductions under this membership that reached the mutual stage or later), a computed `guarantee_met` flag (true once `credits_consumed_committed` reaches the snapshotted `guaranteed_introductions`), and a `refund_cents` field that remains 0 until the membership is cancelled.

A member's `term_end_at` is the membership's `start_at` plus the plan's `term_months` whole calendar months plus the member's `frozen_days_total` in days; it is null whenever the member has no active membership. The member also exposes the computed guarantee figures `guarantee_remaining_committed` and `guarantee_remaining_forecast`, the coaching-discipline fields `no_show_strikes` and `coaching_suspended`, the refund balance `wallet_credit_cents`, and the cumulative freeze total `frozen_days_total`, all described where their owning workflow lives.

### 3.3. Preferences and Compatibility

Before a member can be paired, their matching preferences should be on file. A `Member` (for their own profile) or a `Matchmaker` may create or replace a member's `Preference` row through an idempotent upsert that supplies `seeking_gender` (`MALE`, `FEMALE`, `NONBINARY`, or `ANY`), a `min_age` of at least 18, a `max_age` that must be at least the `min_age`, a `max_distance_band` between 0 and 3 inclusive (0 meaning same city, 3 meaning anywhere), an `attribute_weights` object (a self-declared vector of `education`, `lifestyle`, and `values`, each 0 to 100), and an optional `dealbreaker_tags` array of string tags (defaulting to an empty array). A candidate who carries any tag in this list among their own `attribute_weights` keys is disqualified from a pairing. Reading a member's preferences returns an array of zero or one row.

When a `Matchmaker` suggests an introduction, the system computes a symmetric **compatibility score** for the pair, carried to two decimal places with round-half-up, from four sub-scores that are each derived to a 0-to-100 scale and then blended by fixed weights. The attribute-match sub-score is 100 multiplied by one minus the normalized L1 distance between the two members' `attribute_weights` vectors over their shared keys among `education`, `lifestyle`, and `values`; if the two members share no keys, the attribute-match sub-score is 0. The preference-overlap sub-score is 100 when each member's gender satisfies the other's `seeking_gender` (a `seeking_gender` of `ANY` is always satisfied) **and** each member's age falls within the other's `min_age`-to-`max_age` band; otherwise it is a partial score equal to 50 if the gender condition holds for both plus a further 50 if the age condition holds for both. The location-proximity sub-score is 100 when both members are in the same city, and otherwise 100 minus 25 times the gap between the two cities' proximity-band indices, floored at 0. The activity-recency sub-score is 100 when both members are `ACTIVE`, and 50 when one of them is `FROZEN`, derived from their statuses.

The final compatibility score is the attribute-match sub-score times 0.40, plus the preference-overlap sub-score times 0.35, plus the location-proximity sub-score times 0.15, plus the activity-recency sub-score times 0.10, with the resulting total rounded half-up to two decimal places. This blended figure is stored as the introduction's `compatibility_score`. An introduction may be suggested only when its compatibility score is at least 70.00 — the threshold is inclusive, so exactly 70.00 is eligible and anything below it is not; a sub-threshold pair is rejected with `ERR_COMPATIBILITY_TOO_LOW`.

### 3.4. Suggesting an Introduction: Eligibility, Credits, and the Guarantee Pool

Suggesting an introduction is a `Matchmaker` action and the most heavily guarded operation in the system. The payload names the pair as `member_a_id` and `member_b_id` (member A being the suggestion-initiator side whose guarantee pool is drawn), an optional `win_back_promo` flag (defaulting to `false`), and the mandatory `expected_member_a_version` for the concurrency check described in §2.10.

The two parties must be distinct existing members; a request whose `member_a_id` equals its `member_b_id` is rejected with `ERR_SELF_INTRODUCTION`. Both parties must be eligible: each must be in status `ACTIVE` with an `APPROVED` screening, or the request fails with `ERR_MEMBER_NOT_ELIGIBLE`. The pairing must satisfy preferences mutually — each member's gender must satisfy the other's `seeking_gender` and each member's age must sit within the other's accepted band — or the request fails with `ERR_PREFERENCE_MISMATCH`. Neither party may carry a tag that appears in the other's `dealbreaker_tags`, or the request fails with `ERR_DEALBREAKER`. If either party has a flagged background check, suggestion is blocked with `ERR_BACKGROUND_FLAGGED`. A frozen member cannot have new suggestions raised against them; the operation is blocked with `ERR_MEMBER_FROZEN`. The compatibility threshold of §3.3 then applies. Per the precedence in §2.8, these gates fire in order, so a referential failure surfaces before a safety failure, which surfaces before the compatibility check, which surfaces before the guarantee check, which surfaces before the version check.

If the gates pass, the system computes how many guarantee credits this introduction draws and records the figure on the introduction as `credits_consumed`. The base cost is determined by three interacting inputs. When the introduction's `win_back_promo` flag is set, the cost is 0 (a re-engagement promotion). Otherwise, when member A's plan has `priority_match_enabled`, the cost is 2; otherwise the cost is 1. The amount actually consumed is the smaller of that base cost and member A's current `guarantee_remaining_forecast`, so a suggestion never over-draws the pool; the consumed amount is then subtracted from member A's `guarantee_remaining_forecast`, floored at 0. For example, with five forecast credits remaining on a priority plan the suggestion consumes 2 and leaves 3; with one forecast credit remaining on a priority plan it consumes 1 (capped) and leaves 0; a win-back suggestion consumes 0 regardless.

A guarantee guard sits above this: unless the introduction is a win-back promotion (cost 0), the introduction's credit cost must not exceed member A's `guarantee_remaining_forecast`. A suggestion whose cost would exceed the forecast pool is rejected with `ERR_GUARANTEE_EXHAUSTED` and HTTP status 402. On success the introduction is created in status `SUGGESTED` with both `a_response` and `b_response` at `PENDING`, member A's `guarantee_remaining_forecast` is decremented, member A's `version` is incremented by one, and the introduction's own `version` starts at 1.

The two guarantee figures are computed by aggregation over member A's introductions. The committed-consumed total is the sum of `credits_consumed` over introductions where the member is member A and whose status is `MUTUAL` (or closed after having been mutual); `guarantee_remaining_committed` is the snapshotted `guaranteed_introductions` minus that committed total, floored at 0. The forecast-consumed total is the sum of `credits_consumed` over introductions where the member is member A and whose status is `SUGGESTED`, `ONE_SIDED`, or `MUTUAL`; `guarantee_remaining_forecast` is the snapshotted `guaranteed_introductions` minus that forecast total, floored at 0. Introductions that declined or were closed below the mutual stage are excluded from both sums because their credits were refunded. As an illustration, with a guarantee of eight, three mutual introductions consuming three credits and two still-open suggested introductions consuming two more, the committed remaining is five while the forecast remaining is three. These figures are recomputed whenever an introduction crosses into the mutual, declined, or closed state.

### 3.5. Responding to Introductions: the Two-Party Negotiation

An introduction is a quorum-of-two negotiation, and only the two parties may respond. A `Member` responds by supplying a `response` of `ACCEPTED` or `DECLINED` together with the mandatory `expected_introduction_version`. The responder must be member A or member B of the introduction — anyone else is rejected with `ERR_NOT_INTRODUCTION_PARTY` — and their own prior response must still be `PENDING`; a second response from the same party is rejected with `ERR_ALREADY_RESPONDED`. The acting member must be `ACTIVE`; a frozen member is blocked with `ERR_MEMBER_FROZEN`. A response against an introduction that is no longer open (already declined or closed, or otherwise not in a respondable state) is rejected with `ERR_INVALID_INTRODUCTION_STATE`. The introduction must still be open for the relevant branch, and the version carried must match per §2.10 or the response is rejected with `ERR_STALE_VERSION`.

The first accept moves the introduction from `SUGGESTED` to `ONE_SIDED`, recording that party's response as `ACCEPTED`. The second accept — by the other party — completes the quorum: with both `a_response` and `b_response` now `ACCEPTED`, the introduction advances from `SUGGESTED` or `ONE_SIDED` to `MUTUAL`. Reaching `MUTUAL` commits this introduction's `credits_consumed` against member A's membership; member A's `credits_consumed_committed` is recomputed, and if it reaches the snapshotted `guaranteed_introductions` the membership bubbles up to `FULFILLED` (with `guarantee_met` set true). Once mutual, either party may schedule a date.

A decline by either party, from `SUGGESTED` or `ONE_SIDED`, records that party's response as `DECLINED` and moves the introduction to `DECLINED`. A decline refunds this introduction's `credits_consumed` back to member A's guarantee — the forward consumption at suggestion time is reversed by a compensating refund, so member A's `guarantee_remaining_forecast` is restored.

An introduction may also be closed administratively by a `Matchmaker`, and is closed automatically by the system when a party member exits or when that member's background check comes back flagged. Closing applies to an introduction in `SUGGESTED`, `ONE_SIDED`, or `MUTUAL`, moving it to `CLOSED`. If the introduction's status before closing was below `MUTUAL`, its `credits_consumed` are refunded to member A's guarantee; if it was already `MUTUAL`, no refund occurs because those credits are already committed. Any scheduled date on a closed introduction is cancelled as a cascade.

### 3.6. Dates: Scheduling, Outcomes, and Calendars

Once an introduction is `MUTUAL`, a `Member` party or a `Matchmaker` may schedule a `DateEvent` for it. The payload names the `scheduled_by_member_id` — which must equal member A or member B of the introduction, else `ERR_NOT_INTRODUCTION_PARTY` — together with `start_at` (which must be at or after the clock's current instant) and `end_at`. The interval is half-open, written `[start_at, end_at)`, and `end_at` must be strictly after `start_at`. A new date is created in status `SCHEDULED`, with `outcome` `NONE`, and it occupies the scheduling member's calendar interval; the date records its parent introduction through the `introduction_id` foreign key, as does each feedback entry below.

Calendar overlap is enforced for the scheduling member. A new date must not overlap any existing `SCHEDULED` date or any `BOOKED` coaching session of that member; because intervals are half-open, two intervals that merely touch at an endpoint do not collide, but any true overlap is rejected with `ERR_DATE_OVERLAP`.

A `Matchmaker` records a date's outcome. Recording an outcome of `COMPLETED` or `NO_SHOW` requires the date to be `SCHEDULED` (else `ERR_DATE_NOT_SCHEDULED`) and the clock to have reached the date's `start_at` (else `ERR_DATE_NOT_STARTED`); the supplied `outcome` is set and the matching terminal `status` (`COMPLETED` or `NO_SHOW`) is recorded. A date no-show carries **no** coaching consequence — it does not add coaching strikes, which arise only from coaching-session no-shows. A `Member` party or `Matchmaker` may cancel a `SCHEDULED` date (else `ERR_DATE_NOT_SCHEDULED`); cancellation sets `outcome` and `status` to `CANCELLED` and frees the member's calendar interval. A scheduled date is also cancelled automatically as a cascade when its introduction is closed or its member exits.

After a date, a `Member` party may submit `Feedback` on the introduction, supplying `author_member_id` (which must equal member A or member B of the introduction, else `ERR_NOT_INTRODUCTION_PARTY`), a `rating` from 1 to 5 inclusive, a boolean `continue_interest` indicating whether they want to keep seeing the match, and optional free-text `comments` (defaulting to an empty string).

### 3.7. Coaching: Booking, Strikes, and Suspension

A `Matchmaker` or a `Member` may book a `CoachingSession` for a member, supplying the `coach_user_id` (the opaque Matchmaker operator who will run it) and the session's `start_at` and `end_at`, where `start_at` must be at or after the clock's current instant and `end_at` strictly after `start_at`. A booked session occupies the member's calendar interval and begins in status `BOOKED`.

Two guards apply at booking. First, the member's coaching must not be suspended: booking is refused with `ERR_COACHING_SUSPENDED` whenever the member's `coaching_suspended` flag is set, which happens when their `no_show_strikes` count is at least 3. Second, a new coaching session must keep a 30-minute buffer from the member's scheduled dates: the gap between the new session and any `SCHEDULED` date of the member must be at least 30 minutes, where the buffer is closed so a gap of exactly 30 minutes is allowed but a 29-minute gap collides, and a violation is rejected with `ERR_COACHING_BUFFER_CONFLICT`. A coaching session must also not overlap the member's other scheduled dates or booked sessions on the same half-open-interval basis.

A `Matchmaker` records a coaching outcome. Recording an outcome of `HELD` or `NO_SHOW` requires the session to be `BOOKED` (else `ERR_SESSION_NOT_BOOKED`) and the clock to have reached the session's `start_at`. A `HELD` outcome simply moves the session to `HELD`. A `NO_SHOW` outcome moves the session to `NO_SHOW` and increments the member's `no_show_strikes` by one; if the resulting count reaches at least 3, the member's `coaching_suspended` flag becomes true. A `Member` or `Matchmaker` may cancel a `BOOKED` session (else `ERR_SESSION_NOT_BOOKED`); cancellation moves it to `CANCELLED`, frees the calendar interval, and adds no strike.

Strikes decay over time. The member's effective strike count is computed from their no-show coaching sessions and the clock: take the most recent `start_at` among the member's `NO_SHOW` coaching sessions; if there are none, the effective strike count is 0. Otherwise it is the recorded strike count reduced by one for every full 30 days elapsed since that most recent no-show instant, floored at 0. The `coaching_suspended` flag is true exactly when the resulting `no_show_strikes` is at least 3. Thus, two strikes do not suspend, three do, and after 30 clean days one strike decays away.

### 3.8. Pause and Freeze: Extending the Term

A membership can be paused through a `Freeze` window. A `BillingAdmin` schedules a freeze on a membership by supplying `start_at` (which must be at or after the clock's current instant) and `end_at` (strictly after `start_at`); the freeze interval is half-open `[start_at, end_at)`. Each freeze records its parent membership through the `membership_id` foreign key. A freeze is created in status `SCHEDULED`. If the supplied `start_at` is already at or before the clock's current instant, the freeze becomes `ACTIVE` immediately, which flips the membership to `FROZEN` and the member to `FROZEN`.

A scheduled freeze also activates lazily: once the clock reaches the freeze's `start_at`, the next operation touching the record flips the freeze to `ACTIVE`, the membership to `FROZEN`, and the member to `FROZEN`. While frozen, open suggested or one-sided introductions for the member are not advanced, and new suggestions against the member are blocked with `ERR_MEMBER_FROZEN`.

A `BillingAdmin` resumes an active freeze. Resuming requires the freeze to be `ACTIVE` (else `ERR_FREEZE_NOT_ACTIVE`). On resume, the freeze's `committed_days` is computed as the whole number of days from `start_at` up to the earlier of the freeze's `end_at` and the resume instant, rounded up to the next whole day. The freeze moves to `RESUMED`, those `committed_days` are added to the member's `frozen_days_total`, the member's `term_end_at` is recomputed to reflect the extension, the membership returns to `ACTIVE`, and the member returns to `ACTIVE`. A `BillingAdmin` may instead cancel a freeze that has not yet activated; cancelling requires the freeze to be `SCHEDULED` (else `ERR_FREEZE_NOT_CANCELLABLE`), moves it to `CANCELLED`, and grants no term extension.

### 3.9. Membership Endgame: Fulfilment, Cancellation, Expiry, and Member Exit

A membership reaches `FULFILLED` automatically the moment an introduction's transition to `MUTUAL` raises `credits_consumed_committed` to at least the snapshotted `guaranteed_introductions`; at that point `guarantee_met` is set true. A membership in `ACTIVE` whose term has run out with the guarantee unmet — that is, the clock has reached or passed the member's `term_end_at` — flips to `EXPIRED`; this is evaluated lazily on the next read or operation that touches the membership after the clock advances past `term_end_at`.

A `BillingAdmin` may cancel a membership directly, without exiting the member. Cancellation requires the membership to be `ACTIVE` or `FROZEN` (else `ERR_MEMBERSHIP_NOT_CANCELLABLE`); it computes the refund, records it on the membership's `refund_cents`, moves the membership to `CANCELLED`, and credits the refund to the member's `wallet_credit_cents`.

The refund is computed in two parts against the plan snapshot, the elapsed time versus the clock, and the member's coaching consumption. First, the months part: count the elapsed whole days as the floor of the number of days from the membership's `start_at` to the clock's current instant, then the elapsed full months as the floor of those elapsed days divided by 30 (a 30-day month basis). The remaining months are the plan's `term_months` minus the elapsed full months minus one, floored at 0, and the months refund is the remaining months multiplied by the plan's `monthly_fee_cents` (integer cents, no rounding). Second, the coaching part: the per-session rate is the plan's `coaching_value_cents` divided by its `included_coaching_sessions` (a fractional value), and the unused sessions are the plan's `included_coaching_sessions` minus the count of the member's coaching sessions whose status is `HELD` or `NO_SHOW` (booked and cancelled sessions do not consume). The coaching refund is computed by rounding the per-session rate half-up **for each** unused session line and then summing those rounded lines — this round-per-line-then-sum order is pinned and must not be replaced by rounding the product of the rate and the unused count. The total `refund_cents` is the months refund plus the coaching refund. As a worked example, with a coaching value of 5000 cents over 3 included sessions the per-session rate is 1666.6667; with 3 unused sessions, rounding each line gives 1667 and summing gives 5001 — not the 5000 that rounding the product would yield, so the pinned result is 5001.

Member exit is a `BillingAdmin` action that ends the relationship and triggers the deepest cascade in the system. Exit requires the member to be `ACTIVE` or `FROZEN` (else `ERR_MEMBER_NOT_EXITABLE`). On exit the member moves to `EXITED`; the member's `version` is incremented by one. The member's `ACTIVE` or `FROZEN` membership is cancelled with the same refund computation above, the refund recorded on `refund_cents` and credited to `wallet_credit_cents`. Every `SUGGESTED` or `ONE_SIDED` introduction for the member is closed as a cascade, and each such closed introduction — being below the mutual stage — refunds its consumed credits; every `SCHEDULED` date on the member's introductions is cancelled, and every `BOOKED` coaching session for the member is cancelled. This is the depth-three cascade: member exit closes introductions, and closing an introduction cancels its scheduled date.

### 3.10. The Background-Check Add-On

The optional background check is ordered by a `ScreeningOfficer` or by the `Member` themselves, supplying a `provider_ref` external reference string. Ordering creates a `BackgroundCheck` in status `ORDERED`, with `result` `NONE`, and charges the add-on fee: `fee_charged_cents` is snapshotted from the plan's `background_check_addon_cents` at order time.

A `ScreeningOfficer` completes an ordered check by supplying a `result` of `CLEAR` or `FLAGGED`. Completion requires the check to be `ORDERED` (else `ERR_CHECK_NOT_ORDERED`); the `result` is set and the `status` becomes `COMPLETED`. When the result is `FLAGGED`, every open `SUGGESTED` or `ONE_SIDED` introduction for the subject member is closed as a cascade, each with its credit refund. A `ScreeningOfficer` may instead cancel an ordered check (else `ERR_CHECK_NOT_ORDERED`), which moves it to `CANCELLED` and refunds the `fee_charged_cents` back to the member's `wallet_credit_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource, including state transitions and lifecycle actions, return `200 OK`. The administrative clock-setting capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a supplied UTC instant | BillingAdmin |
| POST | `/membership-plans` | Create a membership plan | BillingAdmin |
| GET | `/membership-plans` | List membership plans (excludes archived unless requested) | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| GET | `/membership-plans/{id}` | Get a membership plan | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/membership-plans/{id}/archive` | Archive a plan (soft delete) | BillingAdmin |
| GET | `/membership-plans/{id}/memberships` | List memberships purchased on a plan | BillingAdmin, Matchmaker, ScreeningOfficer |
| POST | `/members` | Register a prospect member | ScreeningOfficer, Matchmaker |
| GET | `/members` | List members (optional status filter) | BillingAdmin, Matchmaker, ScreeningOfficer |
| GET | `/members/{id}` | Get a member (computed fields included) | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/members/{id}/exit` | Exit a member; cancels membership and cascades | BillingAdmin |
| POST | `/members/{id}/screenings` | Open a screening for a prospect | ScreeningOfficer |
| GET | `/members/{id}/screenings` | List a member's screenings | BillingAdmin, Matchmaker, ScreeningOfficer |
| POST | `/members/{id}/screenings/{screeningId}/decide` | Approve or reject a screening | ScreeningOfficer |
| PUT | `/members/{id}/preferences` | Create or replace a member's preferences | Member, Matchmaker |
| GET | `/members/{id}/preferences` | Get a member's preferences | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/members/{id}/memberships` | Activate a membership for an approved member | BillingAdmin |
| GET | `/members/{id}/memberships` | List a member's memberships | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| GET | `/memberships/{id}` | Get a membership | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/memberships/{id}/cancel` | Cancel a membership (refund to wallet) | BillingAdmin |
| POST | `/memberships/{id}/freezes` | Schedule a freeze window | BillingAdmin |
| GET | `/memberships/{id}/freezes` | List freezes for a membership | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/memberships/{id}/freezes/{freezeId}/resume` | Resume from an active freeze | BillingAdmin |
| POST | `/memberships/{id}/freezes/{freezeId}/cancel` | Cancel a scheduled freeze | BillingAdmin |
| POST | `/introductions` | Suggest an introduction between two members | Matchmaker |
| GET | `/introductions` | List introductions (optional party/status filters) | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| GET | `/introductions/{id}` | Get an introduction | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/introductions/{id}/respond` | Respond to an introduction | Member |
| POST | `/introductions/{id}/close` | Close an introduction | Matchmaker |
| POST | `/introductions/{id}/feedback` | Submit feedback on an introduction | Member |
| GET | `/introductions/{id}/feedback` | List feedback for an introduction | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/introductions/{id}/date-events` | Schedule a date for a mutual introduction | Member, Matchmaker |
| GET | `/introductions/{id}/date-events` | List date events for an introduction | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| GET | `/date-events/{dateEventId}` | Get a date event | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/date-events/{dateEventId}/outcome` | Record a date outcome | Matchmaker |
| POST | `/date-events/{dateEventId}/cancel` | Cancel a scheduled date | Member, Matchmaker |
| POST | `/members/{id}/coaching-sessions` | Book a coaching session | Matchmaker, Member |
| GET | `/members/{id}/coaching-sessions` | List coaching sessions for a member | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| GET | `/coaching-sessions/{sessionId}` | Get a coaching session | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/coaching-sessions/{sessionId}/outcome` | Record a coaching outcome | Matchmaker |
| POST | `/coaching-sessions/{sessionId}/cancel` | Cancel a booked coaching session | Member, Matchmaker |
| POST | `/members/{id}/background-checks` | Order the background-check add-on | ScreeningOfficer, Member |
| GET | `/members/{id}/background-checks` | List background checks for a member | BillingAdmin, Matchmaker, ScreeningOfficer, Member |
| POST | `/members/{id}/background-checks/{checkId}/complete` | Complete a background check | ScreeningOfficer |
| POST | `/members/{id}/background-checks/{checkId}/cancel` | Cancel an ordered background check | ScreeningOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_SCREENING_NOT_FOUND` | 404 Not Found |
| `ERR_INTRODUCTION_NOT_FOUND` | 404 Not Found |
| `ERR_FREEZE_NOT_FOUND` | 404 Not Found |
| `ERR_DATE_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_PROSPECT` | 409 Conflict |
| `ERR_MEMBER_FROZEN` | 409 Conflict |
| `ERR_MEMBER_NOT_EXITABLE` | 409 Conflict |
| `ERR_SCREENING_ALREADY_DECIDED` | 409 Conflict |
| `ERR_MEMBER_NOT_APPROVED` | 409 Conflict |
| `ERR_INVALID_INTRODUCTION_STATE` | 409 Conflict |
| `ERR_ALREADY_RESPONDED` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_FREEZE_NOT_ACTIVE` | 409 Conflict |
| `ERR_FREEZE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DATE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DATE_NOT_STARTED` | 409 Conflict |
| `ERR_SESSION_NOT_BOOKED` | 409 Conflict |
| `ERR_CHECK_NOT_ORDERED` | 409 Conflict |
| `ERR_COACHING_SUSPENDED` | 409 Conflict |
| `ERR_SELF_INTRODUCTION` | 422 Unprocessable Entity |
| `ERR_NOT_INTRODUCTION_PARTY` | 422 Unprocessable Entity |
| `ERR_PLAN_ARCHIVED` | 422 Unprocessable Entity |
| `ERR_MEMBER_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PREFERENCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DEALBREAKER` | 422 Unprocessable Entity |
| `ERR_BACKGROUND_FLAGGED` | 422 Unprocessable Entity |
| `ERR_COMPATIBILITY_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_DATE_OVERLAP` | 409 Conflict |
| `ERR_COACHING_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_GUARANTEE_EXHAUSTED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
