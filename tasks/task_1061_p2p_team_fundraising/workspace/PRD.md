# P2P Team Fundraising API — Product Requirements Document

## 1. Introduction

Charity walk and run events live or die on the strength of their peer-to-peer network. A nonprofit publishes a campaign, individual supporters open personal fundraising pages, those supporters cluster into teams and recruit one another, corporate sponsors put up matching money, and thousands of small gifts arrive over a few weeks. Each of those gifts has to be priced, matched, credited to the right page, receipted for tax purposes, and eventually disbursed to the beneficiary's bank account. Today that work is spread across a donation processor, a spreadsheet of team totals, an email thread with the sponsor about how much of the match pool is left, and a finance team that reconciles everything by hand after the race.

This document specifies the backend service that replaces all of it. The service is a **ledger of record** first and a public engagement surface second: every cent that enters the system is tracked from the donor's card through platform and processing fees, through the sponsor match that may or may not attach to it, through the participant and team credit it produces, through the tax receipt it generates, and finally out through a reviewed, segregated, two-person payout. The public thermometer and leaderboard are projections of that ledger, not independent counters. Because money moves in both directions — refunds unwind matches, revoke incentive awards, void receipts, and restore sponsor pool balances — every rule in this document is written so that the reverse operation is as precisely defined as the forward one.

The service is mounted under `/api` and is consumed by three very different clients: a public campaign website that reads without credentials, an operations console used by the nonprofit's staff, and an internal finance tool used by reviewers who never touch campaign content. The rules below are therefore written from the domain outward: what a campaign manager, a fundraiser, a donor, a finance reviewer and a platform operator are each allowed to do, and exactly what the system does on their behalf.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the service — including public reads — must carry two headers: `X-User-ID` and `X-User-Role`. If either header is absent, or if `X-User-Role` carries a value that is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). There is no implicit anonymous fallback: unauthenticated public traffic must state itself explicitly by sending `X-User-Role: Anonymous`.

The six roles are `PlatformAdmin`, `CampaignManager`, `FinanceReviewer`, `Participant`, `Donor`, and `Anonymous`.

A `PlatformAdmin` is the platform operator. It onboards beneficiary organizations, sets their payout account state, settles and refunds payments, releases and voids disbursements, and drives the logical clock. A `CampaignManager` acts on behalf of a beneficiary nonprofit: it builds and runs campaigns, events, teams, sponsor pools and incentive tiers, and it requests payouts. A `FinanceReviewer` is an independent financial control that reviews, sends back, approves or rejects payout requests and reads the campaign report, and never creates campaign content. A `Participant` is an individual fundraiser acting on their own page and their own registrations. A `Donor` is a giver acting on their own gifts. `Anonymous` is the unauthenticated public surface: it may sign itself up as a participant or a donor and may read public campaign, team, participant, event, leaderboard and thermometer data.

Identity binding differs by role, and this is what ties `X-User-ID` to ownership:

- When `X-User-Role` is `CampaignManager`, `X-User-ID` is the `id` of the acting `Organization`; ownership checks on any resource that references an `Organization` compare the resource's organization reference to `X-User-ID`. Because campaigns, and through them events, teams, pools, tiers, awards, receipts and payouts, all descend from an organization, a campaign manager may only act on campaigns whose `organization_id` equals its own `X-User-ID`.
- When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a `Participant` compare the resource's participant reference to `X-User-ID`. A participant may activate, withdraw and manage only their own page, and may confirm or cancel only registrations whose `participant_id` equals their `X-User-ID`.
- When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting `Donor`; ownership checks on any resource that references a `Donor` compare the resource's `donor_id` to `X-User-ID`. A donor may create gifts under their own donor record and read their own donor profile.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — the payout ledger stores it as `requested_by_user_id`, `reviewed_by_user_id` or `approved_by_user_id` where a transition writes it — but it is never compared to any entity's `id`.
- When `X-User-Role` is `FinanceReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. It is recorded on payouts as `reviewed_by_user_id` and `approved_by_user_id`, and those two recorded values are compared **to each other** for segregation of duties, never to an entity `id`.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity and is never compared to any resource.

When the acting role is not listed among an operation's authorized roles, or when an identity-bound role acts on a resource it does not own, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

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

### 2.3. Pagination

Every collection read accepts two optional query parameters, `limit` and `offset`. When `limit` is omitted it defaults to 10; the smallest accepted value is 1 and the largest accepted value is 100. When `offset` is omitted it defaults to 0, and the smallest accepted value is 0. A `limit` outside the range of 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Collection results are ordered by `created_at` ascending unless a specific ranking is stated for that read — the leaderboard is the only surface in this system that imposes its own ordering. List responses carry `limit`, `offset`, `total_count` and `has_more` in the `meta` object, where `total_count` is the number of rows matching the filters before pagination is applied, and `has_more` states whether any matching rows remain beyond the current window.

### 2.4. Resource Identity, Timestamps and Versioning

Every resource in this system carries a server-minted `id` that is a UUID string with no type prefix; clients never supply an `id`. Every resource also carries `created_at`, `updated_at` and `version`. Both timestamps are ISO 8601 UTC strings with three fractional digits, and `version` is an integer that starts at 1 when the resource is created and increases by 1 on every mutation of that resource. Whenever a mutation touches a resource — whether the client addressed that resource directly or the change reached it through a cascade — the service refreshes that resource's `updated_at` and advances its `version`. All thirteen resource types in this system carry the full set: organizations, campaigns, events, teams, participants, registrations, donors, donations, match pools, incentive tiers, incentive awards, receipts and payouts.

Path parameters are validated left to right. A read or action addressed at a nested path resolves the outermost identifier first, so a request naming a campaign that does not exist fails with `ERR_CAMPAIGN_NOT_FOUND` before any inner identifier is examined. Each resource type raises its own not-found code: `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`, `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404. The same catalogue applies to identifiers supplied inside a request body: when a create names an `organization_id`, `campaign_id`, `event_id`, `team_id`, `participant_id`, `donor_id`, `recruited_by_participant_id`, `captain_participant_id` or `tier_id` that resolves to nothing, the corresponding not-found code is returned.

### 2.5. The Logical Clock

Time in this system is explicit rather than ambient. The server keeps a logical clock that reads exactly `2026-07-01T00:00:00Z` at startup and never falls back to wall-clock time. A platform operator may move that clock to any instant by supplying a `to_iso8601` value; the response reports the new `current_utc`. Every subsequent temporal comparison in this document — early-bird pricing, sponsor pool windows, event start and end gates, the refund window, and every `*_at` stamp the system writes — reads the logical clock, never the host's real time.

### 2.6. Money, Rounding and Cent Arithmetic

All monetary values in this system are integers denominated in whole cents; there are no floating-point money fields and no decimal-place formatting concerns in the API. Where a rule multiplies a cent amount by a percentage or a ratio, the product is rounded to a whole number of cents using **round half up** — a computed value of exactly one-half cent rounds away from zero to the next whole cent.

Two rounding-order rules are pinned because they produce different totals from identical inputs. First, when a value is the sum of several independently derived components, each component is rounded to whole cents **before** the addition, and the resulting sum is never re-rounded. Second, when a campaign-level total is derived from many rows, the system sums the values already stored on each row rather than recomputing an aggregate from raw inputs and rounding once at the end — round per line, then sum.

Percentages exposed to clients are reported in **basis points**: an integer where 10000 basis points represents 100 percent. Basis-point values are always floored to a whole number, never rounded.

### 2.7. Campaign Containment

A campaign is the containment boundary of this system. Events, teams, participants, sponsor match pools, incentive tiers, donations, receipts and payouts all belong to exactly one campaign, and cross-campaign references are never valid. Whenever an operation joins two resources — a registration joining a participant to an event, a participant joining a team, a team naming a captain, a donation naming its designation target — the service verifies that both sides resolve to the **same** campaign before any state changes. These checks produce distinct codes so a client can tell what went wrong: `ERR_EVENT_CAMPAIGN_MISMATCH` when a registration's event and participant belong to different campaigns, `ERR_TEAM_CAMPAIGN_MISMATCH` when a participant's team or a team's captain belongs to another campaign, `ERR_SELF_RECRUIT` when a recruiter reference is invalid, and `ERR_DESIGNATION_UNRESOLVABLE` when a gift's designation target cannot be resolved inside its own campaign. All four carry HTTP 422.

Child resources may only be created while their campaign is in `PUBLISHED` status. Attempting to create a donation, participant, team, event, registration, match pool or incentive tier under a campaign that is still `DRAFT`, or that has already moved to `CLOSED`, is rejected with `ERR_CAMPAIGN_NOT_PUBLISHED` (HTTP 409).

### 2.8. Order of Evaluation

When several rules could reject the same request, they are evaluated in a fixed order so that clients see the most fundamental problem first. The order is:

1. **Authentication** — headers present and role recognized, otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is permitted on this operation and, for the identity-bound roles, owns the target, otherwise `ERR_UNAUTHORIZED`.
3. **Request shape** — required fields present, types correct, enum members recognized, and declared numeric ranges honored, otherwise `ERR_INVALID_REQUEST`. The ranges enforced at this step are: a gift's `amount_cents` is at least 100; a campaign's or team's `goal_amount_cents` is at least 1; a participant's `personal_goal_cents` is at least 1; an event's `capacity` is at least 1; an event's `registration_fee_cents` is at least 0; a campaign's `fundraising_minimum_cents` is at least 0; a gift's `benefit_value_cents` is at least 0; a pool's `pool_amount_cents` and `per_donation_cap_cents` are each at least 1 and its `min_donation_cents` is at least 0; a pool's `match_ratio` is greater than 0 and at most 5; an incentive tier's `threshold_cents` is at least 1; a payout's `amount_cents` is at least 1; an end instant is strictly after its matching start instant; `limit` falls within 1 through 100 and `offset` is at least 0.
4. **Path existence** — every templated path segment resolves, left to right, otherwise the matching not-found code.
5. **Body reference existence** — every identifier supplied in the body resolves, otherwise the matching not-found code.
6. **State admissibility** — the target is in a state that admits the requested transition, otherwise `ERR_INVALID_STATE` (HTTP 409), except on the refund path where the dedicated code `ERR_DONATION_NOT_REFUNDABLE` (HTTP 409) is returned instead.
7. **Cross-aggregate referential integrity** — the campaign-containment checks of §2.7.
8. **Segregation of duties** — the approver-is-not-reviewer check, `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
9. **Temporal windows** — the refund window, sponsor pool window overlap, and the buffered registration conflict check.
10. **Campaign publication and participant readiness** — `ERR_CAMPAIGN_NOT_PUBLISHED` and `ERR_PARTICIPANT_NOT_ACTIVE`.
11. **Duplicate registration** — `ERR_DUPLICATE_REGISTRATION`.
12. **Event capacity** — `ERR_EVENT_AT_CAPACITY`.
13. **Fiscal floors** — the fundraising minimum on registration confirmation and the payout minimum on payout requests.
14. **Balance sufficiency** — `ERR_INSUFFICIENT_CAMPAIGN_BALANCE`.
15. **Payout account readiness** — `ERR_ORGANIZATION_PAYOUT_UNVERIFIED`.
16. **Stale-version rejection** — the optimistic concurrency check described in §2.9.

The practical consequences matter. A refund request against a gift that was never settled surfaces as `ERR_DONATION_NOT_REFUNDABLE` rather than as a window or balance complaint, because state admissibility runs before any window arithmetic. A payout request that is both below the fiscal floor and larger than the available balance surfaces as `ERR_PAYOUT_BELOW_MINIMUM`, because the floor is checked first. A registration for a participant who is not yet ready, at an event that is also full, surfaces the readiness problem first. And because the stale-version check sits last, a payout request that is stale **and** below the minimum reports the minimum violation.

### 2.9. Optimistic Concurrency on Payout Creation

Requesting a disbursement is the one write in this system guarded by optimistic concurrency, because a new request legitimately supersedes any prior open request of the same campaign and therefore cannot be blocked by a state precondition. The request must carry `expected_campaign_version`, a non-optional field holding the `version` of the campaign as the client last observed it. If that value does not equal the campaign's current `version`, the request is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412) and nothing is created. The purpose is to stop a requester from disbursing against a balance that has moved since they read it: a settle, a refund, a release or a void all advance the campaign's `version`, so any of them invalidates a payout request built on the older figure. A successful payout request itself increments the campaign's `version` by 1. No other endpoint in this system accepts a version field, and no other endpoint returns HTTP 412.

### 2.10. The Fund Conservation Identity

The service maintains four money figures on every campaign, all in whole cents: `lifetime_net_cents`, `reserved_payout_cents`, `paid_out_cents` and `available_balance_cents`. `lifetime_net_cents` is the sum, over the campaign's gifts whose payment dimension reads `SETTLED`, of that gift's `net_cents` added to its `matched_amount_cents`. `reserved_payout_cents` is the sum of `amount_cents` across the campaign's payouts sitting in `REQUESTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED` or `APPROVED`. `paid_out_cents` is the sum of `amount_cents` across the campaign's payouts in `RELEASED`. Payouts in `REJECTED`, `VOIDED` or `SUPERSEDED` contribute to neither figure. `available_balance_cents` is `lifetime_net_cents` reduced by `reserved_payout_cents` and reduced again by `paid_out_cents`.

After every mutation — including the compensating pair where a released payout is later voided — the following identity must hold: `available_balance_cents` added to `reserved_payout_cents` added to `paid_out_cents` equals `lifetime_net_cents`. Gifts that are `REFUNDED` or `FAILED` leave the sum entirely; they are not netted out, they simply stop contributing. These figures are recomputed after every gift settlement, every refund, and every payout transition, and they are refreshed before a campaign is returned from a read.

### 2.11. Derived Counters and Cascade Discipline

Several counters in this system are **derived** rather than incremented ad hoc, and the service re-derives them whenever a change could have moved them. An event's `registered_count` is the number of that event's registrations sitting in `RESERVED`, `CONFIRMED` or `CHECKED_IN`, and the event's `status` flips between `OPEN` and `FULL` purely as a function of that count against `capacity`. A team's `member_count` is the number of participants whose team reference points at it and whose own `status` is `PENDING` or `ACTIVE`. A participant's `recruit_count` is the number of participants naming them as recruiter whose own `status` is `PENDING` or `ACTIVE`. A campaign's `donor_count` is the number of distinct givers behind its `SETTLED` gifts. A sponsor pool's `remaining_cents` is its `pool_amount_cents` less its `allocated_cents`, and never goes below zero.

Cascades are ordered and complete. When one operation touches several resources, every touched resource has its `updated_at` refreshed and its `version` advanced, and the ordering given in §3 for each cascade is normative — a downstream step reads the state its upstream step has already written.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Beneficiary and Opening a Campaign

Everything begins with the beneficiary nonprofit. A platform operator registers an `Organization` with its legal `name`, its `ein` (the tax identifier that will be printed on every receipt issued under it), and an operational `contact_email`. The identifier returned by that registration is significant beyond the record itself: it is the value a campaign manager subsequently sends as `X-User-ID`. A newly registered organization begins with `payout_account_status` of `UNVERIFIED`, and only a platform operator may change it, supplying a `status` of either `VERIFIED` or `SUSPENDED`. `VERIFIED` unlocks disbursement; `SUSPENDED` blocks it again. The third member of the enumeration, `UNVERIFIED`, is the initial value and cannot be re-selected.

A campaign manager then opens a campaign against its own organization, naming the `organization_id`, a public `title`, a `goal_amount_cents` target, and optionally a `fundraising_minimum_cents` — the per-participant credited amount each fundraiser must reach before an event registration of theirs may be confirmed. When that minimum is not supplied it defaults to 0, which effectively disables the gate. A new campaign lands in `DRAFT` with `published_at` and `closed_at` both empty, with `receipt_seq` at 0, and with every computed money figure (`raised_credited_cents`, `lifetime_net_cents`, `reserved_payout_cents`, `paid_out_cents`, `available_balance_cents`, `donor_count`) at 0.

Publication moves the campaign `DRAFT → PUBLISHED`. Only the campaign's own manager — the actor whose `X-User-ID` equals the campaign's organization — may do it, only while the campaign is still `DRAFT`, and only when the campaign's goal is at least 1 cent. Publication stamps `published_at` with the current logical-clock instant and is the event that opens the campaign to gifts, fundraiser pages, teams, events, registrations, sponsor pools and incentive tiers. Attempting to publish a campaign that is not `DRAFT` is rejected with `ERR_INVALID_STATE`; attempting it as a manager of a different organization is rejected with `ERR_UNAUTHORIZED`.

Closing moves the campaign `PUBLISHED → CLOSED` and is likewise restricted to the campaign's own manager and to a campaign currently in `PUBLISHED`. Closure stamps `closed_at` and then runs a two-step cascade in this order. **Cascade step 1:** every event of the campaign whose status is `OPEN` or `FULL` transitions to `CLOSED`; existing registrations keep whatever status they hold, but no new registration may be created against a closed event. **Cascade step 2:** every sponsor match pool of the campaign whose status is `ACTIVE` or `EXHAUSTED` transitions to `CLOSED`. After closure, any attempt to create a new gift, participant, team, event or registration under the campaign is rejected with `ERR_CAMPAIGN_NOT_PUBLISHED`, and any attempt to register against one of the cascaded events is rejected with `ERR_INVALID_STATE`. `CLOSED` is terminal for a campaign.

### 3.2. Fundraiser Pages, Teams and the Recruiting Graph

A personal fundraising page is created either by the fundraiser themselves — the public self-signup surface, which is why an unauthenticated caller may create one — or by the campaign's manager on their behalf. The creation names the `campaign_id` and a public `display_name`, and may optionally name a `team_id` to join, a `recruited_by_participant_id` naming the fundraiser who brought them in, and a `personal_goal_cents` target which defaults to 10000 when omitted. The identifier returned is the value that fundraiser will send as `X-User-ID`. A new page starts in `PENDING` with `credited_cents`, `projected_cents` and `recruit_count` at 0 and `minimum_met` false. When a team was named, that team's `member_count` rises by one; when a recruiter was named, the recruiter's `recruit_count` rises by one.

Three referential rules guard page creation. The named team must belong to the same campaign as the page, or the request is rejected with `ERR_TEAM_CAMPAIGN_MISMATCH`. The named recruiter must belong to the same campaign, and must not be the page being created, or the request is rejected with `ERR_SELF_RECRUIT`. And the campaign itself must be `PUBLISHED`, or `ERR_CAMPAIGN_NOT_PUBLISHED` applies.

Activation moves a page `PENDING → ACTIVE`. Only the fundraiser acting on their own page (or the campaign's manager) may do it, the page must currently be `PENDING`, and the campaign must be `PUBLISHED`. Activation is what makes the fundraiser's event registrations confirmable — an inactive page cannot be confirmed onto a start line.

Withdrawal moves a page to `WITHDRAWN`, which is terminal, and is reachable from either `PENDING` or `ACTIVE`. Withdrawing from `PENDING` decrements the `member_count` of the team the page belongs to, if any, and does nothing else. Withdrawing from `ACTIVE` runs a three-step cascade in this order. **Cascade step 1:** every registration of that fundraiser sitting in `RESERVED` or `CONFIRMED` transitions to `CANCELLED`. **Cascade step 2:** each cancelled registration decreases its event's `registered_count` by 1. **Cascade step 3:** each event whose count has now dropped below its `capacity` and whose status was `FULL` transitions `FULL → OPEN`. As with the `PENDING` case, the team's `member_count` is decremented when the page belonged to a team. Money already banked is not clawed back: gifts already `SETTLED` and designated to that fundraiser keep their credit, and the page's `credited_cents` is unchanged by withdrawal.

Teams are created by a campaign manager or by a fundraiser, naming the `campaign_id`, a public team `name`, a `goal_amount_cents` target of at least 1 cent, and optionally a `captain_participant_id`. A captain must already be a fundraiser of the same campaign, or the create is rejected with `ERR_TEAM_CAMPAIGN_MISMATCH`; when no captain is named the field is simply empty. New teams begin `ACTIVE` with `credited_cents` and `member_count` at 0.

Disbanding a team moves it `ACTIVE → DISBANDED`, may only be performed by the manager of the organization behind the team's campaign, and only while the team is `ACTIVE`. Two effects follow: every fundraiser whose team reference points at the team has that reference cleared, so `member_count` becomes 0; and the team's `credited_cents` is recomputed to count **only** gifts designated directly at the team, since it now has no members to aggregate. A `DISBANDED` team is dropped from the leaderboard entirely.

### 3.3. Race Events, Registration and the Early-Bird Price

A campaign manager creates the walk or run itself, supplying the `campaign_id`, an event `name`, the `starts_at` and `ends_at` instants, an `early_bird_ends_at` instant, a `registration_fee_cents` price, and a `capacity`. The end instant must be strictly later than the start instant. New events open in `OPEN` with `registered_count` at 0. An event's `status` moves between `OPEN` and `FULL` purely by re-derivation: the moment a registration is persisted that brings `registered_count` up to `capacity`, the event transitions `OPEN → FULL`, and further registration attempts are rejected with `ERR_EVENT_AT_CAPACITY`; the moment a registration leaves the counted set and the count falls back below `capacity`, a `FULL` event transitions `FULL → OPEN` and accepts registrations again. This `OPEN`/`FULL` cycle is re-evaluated on every registration status change. The only one-way door is `CLOSED`, which an event reaches through the campaign-closure cascade of §3.1 from either `OPEN` or `FULL`.

Reserving a slot is done by the fundraiser or by the campaign manager, naming the `participant_id` and the `event_id`, and optionally setting `minimum_waived`. That flag defaults to false and may only be set true by a campaign manager — it is the manager's override for the fundraising gate described below, and a fundraiser cannot waive their own minimum. A new registration lands in `RESERVED` with `confirmed_at` empty, immediately raising the event's `registered_count` by 1 and flipping the event to `FULL` if the count has reached `capacity`.

Four guards run before a reservation is accepted, in the precedence of §2.8. The event must belong to the same campaign as the fundraiser, or `ERR_EVENT_CAMPAIGN_MISMATCH` is returned. The fundraiser must not already hold two overlapping commitments: taking each of their registrations in `RESERVED`, `CONFIRMED` or `CHECKED_IN`, the system widens that registration's event window by 90 minutes on each side — from 90 minutes before `starts_at` through 90 minutes after `ends_at` — and rejects the new reservation with `ERR_REGISTRATION_TIME_CONFLICT` if the new event's identically widened window intersects it. Both ends of these buffered windows are inclusive, so two events whose buffered windows merely touch at a single instant are still a conflict. Next, a fundraiser may hold at most one registration in `RESERVED`, `CONFIRMED` or `CHECKED_IN` for the same event; a second attempt is rejected with `ERR_DUPLICATE_REGISTRATION`. Finally, the event's `registered_count` must be strictly below `capacity` at the moment of persistence, or `ERR_EVENT_AT_CAPACITY` applies.

The price is stamped once, at reservation time, into `fee_charged_cents`, and never recomputed afterwards. If the current logical-clock instant is **strictly earlier** than the event's `early_bird_ends_at`, the fundraiser earns the early-bird discount of 20 percent: the discount is the event's `registration_fee_cents` multiplied by 20 percent, rounded half up to whole cents, and `fee_charged_cents` is `registration_fee_cents` reduced by that rounded discount. Otherwise `fee_charged_cents` is the undiscounted `registration_fee_cents`. At exactly the `early_bird_ends_at` instant the discount does **not** apply.

Confirmation moves a registration `RESERVED → CONFIRMED` and is performed by the fundraiser or the campaign manager. It requires the registration to be `RESERVED`, the fundraiser's page to be `ACTIVE` (otherwise `ERR_PARTICIPANT_NOT_ACTIVE`), the event to be `OPEN` or `FULL` — a full event still admits confirmations of slots already reserved — and the fundraising gate to pass. That gate is satisfied when the registration's `minimum_waived` is true, **or** when the fundraiser's `credited_cents` is greater than or equal to the campaign's `fundraising_minimum_cents`; exactly meeting the minimum passes. A confirmation that fails the gate is rejected with `ERR_FUNDRAISING_MINIMUM_NOT_MET`. Success stamps `confirmed_at` with the current logical-clock instant.

On race day, the campaign manager records attendance, moving a registration `CONFIRMED → CHECKED_IN`. The registration must be `CONFIRMED`, the fundraiser's page must be `ACTIVE`, and the current logical-clock instant must be at or after the event's `starts_at` — checking in before the gun is not permitted. A checked-in registration is counted as attended in the campaign rollup, and `CHECKED_IN` is terminal; notably it still occupies a slot in `registered_count`.

Absence is recorded after the fact: a campaign manager moves a `CONFIRMED` registration to `NO_SHOW`, but only once the current logical-clock instant is at or after the event's `ends_at`. Marking a no-show decreases the event's `registered_count` by 1 and, when the event was `FULL` and the count now sits below `capacity`, transitions it `FULL → OPEN`. `NO_SHOW` is terminal.

Cancellation is available to the fundraiser or the campaign manager from either `RESERVED` or `CONFIRMED`, and is also the terminus of the withdrawal cascade of §3.2. Either way the registration moves to `CANCELLED`, the event's `registered_count` decreases by 1, and a `FULL` event whose count now sits below `capacity` transitions `FULL → OPEN`. `CANCELLED` is terminal.

### 3.4. Gifts: Intake, Fees and What the Donor Is Actually Charged

A giver is registered as a `Donor` with a `display_name` that will be printed on receipts, an `email` for receipt delivery, and an optional `is_anonymous` flag that defaults to false; when true, the giver's name is suppressed from public donation listings. As with fundraiser pages, the identifier returned is the value the giver sends as `X-User-ID`, and the public may self-register.

A gift names its `campaign_id`, the `donor_id` behind it, a `designation_type` and a `designation_id`, an `amount_cents` of at least 100, an optional `cover_fees` flag defaulting to false, and an optional `benefit_value_cents` defaulting to 0 — the fair market value of any goods or services returned to the giver, which will be subtracted from the deductible amount on the receipt. `amount_cents` is the designated amount: the number the giver intends the campaign to be credited for.

Designation is polymorphic. `designation_type` is one of `CAMPAIGN`, `TEAM` or `PARTICIPANT`, and `designation_id` is resolved according to it — a campaign identifier when `CAMPAIGN`, a team identifier when `TEAM`, a fundraiser page identifier when `PARTICIPANT`. The resolved row must belong to the gift's own campaign. When the identifier does not resolve to a row of the named type inside that campaign, the gift is rejected with `ERR_DESIGNATION_UNRESOLVABLE`.

Fees are computed once, at gift creation, and never recomputed. Two components are derived independently and each is rounded to whole cents by itself before anything is added. The **platform component** is the gift's `amount_cents` multiplied by 5 percent, rounded half up. The **processing component** is the gift's `amount_cents` multiplied by 2.9 percent, rounded half up. The stored `fee_cents` is the platform component plus the processing component plus a flat 30-cent processing charge; that sum is never re-rounded. Whether the fee comes out of the gift or is added on top is the giver's choice: when `cover_fees` is false, `net_cents` — the amount the campaign nets from the gift itself — is `amount_cents` reduced by `fee_cents`; when `cover_fees` is true, `net_cents` is the full `amount_cents`.

What the giver's card is charged follows immediately afterwards, in a single non-iterative pass. When `cover_fees` is true, `charged_amount_cents` is `amount_cents` plus `fee_cents`; otherwise `charged_amount_cents` equals `amount_cents`. The dependency looks circular — the giver is charged more than the designated amount, yet the fee was derived from the designated amount — and it is deliberately pinned open: the fee is a function of `amount_cents` **only**. The system does not re-derive the fee from the charged figure and does not iterate toward a fixed point; exactly one grossing-up pass is performed. The evaluation order is fixed as `fee_cents`, then `net_cents`, then `charged_amount_cents`.

A new gift begins with its payment dimension at `PENDING` and its match dimension at `UNMATCHED`, with `matched_amount_cents` at 0, no pool attached, and both `settled_at` and `refunded_at` empty. Nothing moves in any credited total, thermometer or leaderboard until the gift settles. These two dimensions are genuinely independent: `payment_status` walks `PENDING`, `SETTLED`, `REFUNDED`, `FAILED` while `match_status` walks `UNMATCHED`, `MATCHED`, `NOT_ELIGIBLE`, `REVERSED` on the same row.

### 3.5. Sponsor Match Pools and the Allocation Waterfall

A corporate sponsor's commitment is recorded by the campaign manager as a match pool, naming the `campaign_id`, the `sponsor_name`, the `pool_amount_cents` committed, a `match_ratio` multiplier greater than 0 and at most 5, a `per_donation_cap_cents` ceiling on any single gift's match, an optional `min_donation_cents` floor defaulting to 0, and the `starts_at` and `ends_at` bounds of the matching window. The window is **half-open**: the start instant is inclusive and the end instant is exclusive, and the end must be strictly after the start. A new pool opens `ACTIVE` with `allocated_cents` at 0 and `remaining_cents` equal to `pool_amount_cents`.

Two pools of the same campaign may not have overlapping windows while both are live. A new pool whose half-open window overlaps that of any existing pool of the campaign in `ACTIVE` or `EXHAUSTED` is rejected with `ERR_MATCH_WINDOW_OVERLAP`. Because the windows are half-open, a pool that begins at exactly the instant another pool ends is accepted.

Matching runs only at settlement, immediately after the settled instant is stamped, and it considers pools of the gift's own campaign. A pool is a candidate when all four of these hold: its status is `ACTIVE`; the current logical-clock instant is at or after its `starts_at` and strictly before its `ends_at`; its `remaining_cents` is greater than 0; and the gift's `amount_cents` is greater than or equal to the pool's `min_donation_cents`. Candidates are ranked by `ends_at` ascending — the soonest-expiring sponsor money drains first — and ties on `ends_at` are broken by `created_at` ascending. Exactly one pool, the first in that ranking, is used; the allocation never spills over into a second pool even when the first pool's cap or remaining balance truncates the match.

The applied match is derived as follows. The raw match is the gift's `amount_cents` multiplied by the selected pool's `match_ratio`, rounded half up to whole cents. The stored `matched_amount_cents` is then the smallest of three figures: that rounded raw match, the pool's `per_donation_cap_cents`, and the pool's `remaining_cents`. If the result is at least 1 cent, the gift's `match_pool_id` is set to the chosen pool and its match dimension moves `UNMATCHED → MATCHED`; the pool's `allocated_cents` rises by the matched amount and its `remaining_cents` becomes `pool_amount_cents` less `allocated_cents`; and if `remaining_cents` has reached exactly 0 the pool transitions `ACTIVE → EXHAUSTED` and leaves the candidate set. If the candidate set was empty, or the computed match came out below 1 cent, the match dimension moves `UNMATCHED → NOT_ELIGIBLE`, `matched_amount_cents` stays 0 and no pool is attached — this is not an error and no rejection is raised. A gift whose payment attempt fails also lands its match dimension in `NOT_ELIGIBLE`.

A campaign manager may retire a pool early, moving it `ACTIVE → CLOSED` or `EXHAUSTED → CLOSED`; the campaign-closure cascade does the same thing en masse. A closed pool permanently leaves the candidate set and its `remaining_cents` is frozen at its current value. One subtlety survives closure: a later refund reversal still returns cents to a closed pool's `remaining_cents`, but the pool stays `CLOSED` and never matches again. By contrast, `EXHAUSTED` is not terminal — a refund that returns money to an exhausted pool transitions it `EXHAUSTED → ACTIVE`, and it re-enters the candidate set.

### 3.6. Settlement: Credit, Receipts and Incentives

A platform operator resolves a pending gift by supplying an `outcome` of either `SETTLED` or `FAILED`. Either way the gift must still be `PENDING` in its payment dimension; anything else is rejected with `ERR_INVALID_STATE`. A settlement additionally requires the campaign to be `PUBLISHED`.

A `FAILED` outcome moves the payment dimension `PENDING → FAILED` and the match dimension to `NOT_ELIGIBLE`. No receipt is created, no incentive award is created, and no credited total anywhere moves. `FAILED` is terminal.

A `SETTLED` outcome moves the payment dimension `PENDING → SETTLED` and drives the full cascade, in this order. First, `settled_at` is stamped with the current logical-clock instant — this instant is the anchor of the refund window and the source of the receipt's tax year. Second, the match allocation of §3.5 runs, driving the match dimension to either `MATCHED` or `NOT_ELIGIBLE`. Third, the credited totals of the designation target are recomputed: the designated fundraiser's `credited_cents`, the relevant team's `credited_cents`, and the campaign's `raised_credited_cents`. Fourth, a receipt is issued. Fifth, incentive awards are created for every newly crossed tier.

**Credit.** A fundraiser's `credited_cents` is the sum, across gifts whose `designation_type` is `PARTICIPANT`, whose `designation_id` names that fundraiser, and whose payment dimension reads `SETTLED`, of the gift's `amount_cents` added to its `matched_amount_cents`. Note what this excludes: only `PARTICIPANT`-designated gifts credit an individual — a gift designated at a team or at the campaign as a whole never credits any individual fundraiser. Alongside it, `minimum_met` is true exactly when `credited_cents` is greater than or equal to the campaign's `fundraising_minimum_cents`, and false otherwise. A fundraiser with no settled gifts is credited 0, never a null.

A second, optimistic figure is published alongside it. `projected_cents` is computed the same way but over gifts whose payment dimension is `PENDING` **or** `SETTLED`. For a `SETTLED` gift it uses that gift's actual `matched_amount_cents`, exactly as the credited figure does. For a `PENDING` gift no match has run yet, so it adds a **projected** match: the pool that the allocation rules of §3.5 would select right now is identified, and the projection is the smallest of the gift's `amount_cents` multiplied by that pool's `match_ratio` rounded half up, the pool's `per_donation_cap_cents`, and the pool's `remaining_cents`; when the candidate set is empty the projection is 0. On identical data, `projected_cents` therefore exceeds `credited_cents` whenever any pending gift is outstanding. `credited_cents` is the only figure that gates incentive awards and the fundraising minimum; `projected_cents` is a display figure and gates nothing. Both are refreshed whenever a fundraiser page is read.

**Receipts.** The receipt is minted by the settlement cascade and by nothing else; there is no way for a client to create one directly. The gift's campaign holds a per-campaign counter, `receipt_seq`, which begins at 0 and is increased by exactly 1 for each settlement. The new counter value is formatted as the string `receipt_number`: the literal prefix `RCPT-` followed by the counter value written as a decimal number left-padded with zeros to a width of six digits — the first receipt of a campaign is therefore `RCPT-000001`. This sequence is per-campaign, is assigned in settlement order, is never re-used, is never re-assigned on a reissue, and is never derived from any identifier. The receipt records the `donation_id` it documents and the `campaign_id` it belongs to, carries a `deductible_amount_cents` equal to the gift's `amount_cents` reduced by its `benefit_value_cents` and floored at 0 (never negative), and a `tax_year` equal to the UTC calendar year of the gift's `settled_at`. It opens in `ISSUED` with `issued_at` set to the current logical-clock instant, `voided_at` empty, and `reissue_count` at 0.

A campaign manager or platform operator may void an issued receipt — for a correction request, say — moving it `ISSUED → VOIDED`, which stamps `voided_at` and removes the receipt from the campaign rollup's deductible total. The refund cascade performs the same transition automatically. A voided receipt may be re-issued, moving it `VOIDED → ISSUED`, provided the underlying gift's payment dimension still reads `SETTLED`; a reissue increases `reissue_count` by 1, refreshes `issued_at`, clears `voided_at`, and keeps the **original** `receipt_number` unchanged. This issue-void-reissue loop is a genuine cycle with no terminal state.

**Incentives.** A campaign manager defines the rewards fundraisers can earn as incentive tiers, each naming its `campaign_id`, a tier `name`, a `threshold_cents` of at least 1, and a `reward_description` of what the fundraiser receives. During a settlement, once the designated fundraiser's new `credited_cents` is known, the system examines every incentive tier of that campaign whose `threshold_cents` is less than or equal to that new credited figure, and creates an award in `EARNED` for each such tier for which no award of that fundraiser and tier already exists in a status other than `REVOKED`. Each award records its `participant_id` and `tier_id`, stamps `earned_at` with the current logical-clock instant, and leaves `fulfilled_at` and `revoked_at` empty. Awards are never created by a direct client call; they are discoverable only by reading them back.

Fulfilment is the campaign manager's acknowledgement that the reward has been shipped, moving an award `EARNED → FULFILLED`. The award must be `EARNED`, and the acting manager must be the organization behind the fundraiser's campaign. Fulfilment stamps `fulfilled_at` and, importantly, makes the award permanently immune to the revocation cascade described next.

### 3.7. Refunds and the Unwinding of Everything Downstream

Refunding is a platform-operator action carrying an optional `reason`, and it is the most consequential operation in the system because it must reverse four separate downstream effects.

Three preconditions are checked, in the order of §2.8. The gift's payment dimension must read `SETTLED`; a gift that is `PENDING`, `FAILED` or already `REFUNDED` is rejected with `ERR_DONATION_NOT_REFUNDABLE` before any window arithmetic runs at all. The current logical-clock instant must be at or before the gift's `settled_at` plus a refund window of 60 days; the boundary instant itself is still refundable, and anything later is rejected with `ERR_REFUND_WINDOW_EXPIRED`. Finally, the campaign's `available_balance_cents` must be greater than or equal to the gift's `net_cents` added to its `matched_amount_cents` — a campaign that has already reserved or disbursed the money cannot give it back, and the attempt is rejected with `ERR_INSUFFICIENT_CAMPAIGN_BALANCE`.

When those pass, the payment dimension moves `SETTLED → REFUNDED`, `refunded_at` is stamped with the current logical-clock instant, and two cascades run.

**Cascade A — the sponsor match.** Step 1: when the gift's match dimension reads `MATCHED`, it transitions `MATCHED → REVERSED`. Step 2: that reversal returns the reversed `matched_amount_cents` to the pool's `remaining_cents` and sets the gift's `matched_amount_cents` to 0. Step 3: a pool that had been driven to `EXHAUSTED` and now holds a positive `remaining_cents` transitions `EXHAUSTED → ACTIVE` and re-enters the candidate set for future settlements. A gift whose match dimension was `UNMATCHED` or `NOT_ELIGIBLE` skips this cascade entirely, and — as noted in §3.5 — a pool already in `CLOSED` still receives its cents back but stays `CLOSED`.

**Cascade B — credit and incentives.** Step 1: the credited totals are recomputed downward — the designated fundraiser's `credited_cents` and `projected_cents`, the relevant team's `credited_cents`, and the campaign's `raised_credited_cents`, `lifetime_net_cents`, `available_balance_cents` and `donor_count`. Step 2: every incentive award of that fundraiser sitting in `EARNED` whose tier's `threshold_cents` now exceeds the recomputed `credited_cents` transitions `EARNED → REVOKED` and has `revoked_at` stamped. Awards already in `FULFILLED` are left untouched, and awards already `REVOKED` stay revoked. Revocation is not reversible in place: if a later settlement pushes the fundraiser back over that threshold, a **new** award is created rather than the revoked one being revived. Both `FULFILLED` and `REVOKED` are terminal.

Independently of the two cascades, the receipt attached to the refunded gift transitions `ISSUED → VOIDED`, dropping it out of the campaign rollup's deductible total. Both `REFUNDED` and `FAILED` are terminal for the payment dimension: a refunded gift can never be settled again.

### 3.8. Public Progress Surfaces: Thermometer and Leaderboard

The thermometer is the public progress bar on the campaign page and is readable by anyone, including unauthenticated visitors. It reports the campaign's `goal_amount_cents`, the credited total `raised_credited_cents`, an integer `percent_bp`, a `donor_count` and a `participant_count`. The credited total is the sum, across **all** of the campaign's gifts whose payment dimension reads `SETTLED` regardless of what they were designated at, of `amount_cents` added to `matched_amount_cents`. `donor_count` is the number of distinct givers behind that same set of gifts, counted once each however many gifts they made. `participant_count` is the number of the campaign's fundraiser pages whose status is `PENDING` or `ACTIVE`. Progress is reported in basis points: `percent_bp` is the credited total multiplied by 10000, divided by the campaign's `goal_amount_cents`, and floored to a whole number; the reported value is then capped at 20000 basis points, so a campaign at triple its goal still displays 20000. With zero settled gifts the response reports a credited total of 0, a donor count of 0 and a `percent_bp` of 0 — never a null and never a division failure, which is why a campaign goal of at least 1 cent is enforced at creation.

The leaderboard is likewise public and is the one read in this system that does not sort by `created_at`. The caller must supply a `scope` of either `TEAM` or `PARTICIPANT`, may supply a `variant`, and may page with `limit` and `offset`. The response echoes the `scope` and `variant` in use and carries the ranked `rows`.

Under `scope=TEAM`, each team's score is its `credited_cents`, built from two additive parts: the sum of the `credited_cents` of every fundraiser whose team reference points at that team — that is, the FINAL participant credit of §3.6 — plus the sum, across gifts whose `designation_type` is `TEAM`, whose `designation_id` names that team, and whose payment dimension reads `SETTLED`, of `amount_cents` added to `matched_amount_cents`. Only teams in `ACTIVE` appear; `DISBANDED` teams are excluded from the leaderboard entirely.

Two variants order those teams differently, and the choice can invert the ranking on identical data. `RAW_TOTAL` is the default — the variant used by the public campaign page — and orders teams by `credited_cents` descending, breaking ties by `created_at` ascending; the size of a team's goal is ignored entirely. `GOAL_PERCENT`, requested by passing `variant=GOAL_PERCENT`, is used to award the "closest to goal" challenge: it computes each team's `goal_percent_bp` as that team's `credited_cents` multiplied by 10000, divided by the team's `goal_amount_cents`, floored to a whole basis-point integer, and orders teams by that figure descending, again breaking ties by `created_at` ascending. Because a small team with a modest goal can outrank a much larger team, the two variants can produce opposite orderings from the same underlying data. Under `scope=PARTICIPANT`, rows are built from the FINAL participant credit of §3.6 instead.

### 3.9. Operational Reporting

The campaign rollup is an internal surface — available to the platform operator, the campaign's own manager and the finance reviewer, but not to the public — and it reads across every gift, receipt, registration and incentive award reachable from the campaign, subject to a row limit of 1000 rows per underlying collection. It reports nine figures. `settled_donation_count` and `refunded_donation_count` are the counts of the campaign's gifts whose payment dimension reads `SETTLED` and `REFUNDED` respectively. `gross_amount_cents` is the sum of `amount_cents` over the settled gifts. `fee_total_cents` is the sum of the per-gift `fee_cents` over gifts whose payment dimension is `SETTLED` **or** `REFUNDED` — fees are retained on a refund, and per §2.6 this total is built by summing values already rounded on each row rather than by rounding an aggregate. `match_total_cents` is the sum of `matched_amount_cents` over the settled gifts. `deductible_total_cents` is the sum of `deductible_amount_cents` over the campaign's receipts currently in `ISSUED`, so voided receipts contribute nothing. `confirmed_registrations` counts registrations across the campaign's events sitting in `CONFIRMED` or `CHECKED_IN`, while `checked_in_registrations` counts only those in `CHECKED_IN`. `awards_earned_count` counts incentive awards of the campaign's fundraisers in `EARNED` or `FULFILLED`, so revoked awards drop out.

### 3.10. Disbursement: Request, Review and Release

Money leaves the platform through a request-and-review workflow with a hard segregation-of-duties boundary between the two finance actions.

A campaign manager requests a disbursement against its own campaign, supplying the `amount_cents` sought, the `expected_campaign_version` demanded by §2.9, and an optional free-text `note` justifying the request, which defaults to an empty string. Four things are checked beyond the standard guards. The requested amount must be at least the platform's disbursement floor of 5000 cents, or the request is rejected with `ERR_PAYOUT_BELOW_MINIMUM`. The requested amount must not exceed the campaign's `available_balance_cents`, measured **after** any superseded reservation has been released, or it is rejected with `ERR_INSUFFICIENT_CAMPAIGN_BALANCE`. The version must match, per §2.9. And on success, any existing payout of that campaign sitting in `REQUESTED` or `CHANGES_REQUESTED` transitions to `SUPERSEDED` and its reservation is released from `reserved_payout_cents` — this is why a second request is never blocked by a state precondition. The new payout opens in `REQUESTED` with `requested_by_user_id` set to the acting `X-User-ID`, `reviewed_by_user_id` and `approved_by_user_id` empty, and `released_at` empty; the campaign's `version` advances by 1, and `reserved_payout_cents` and `available_balance_cents` are recomputed. `SUPERSEDED` is terminal.

A finance reviewer picks the request up, moving it `REQUESTED → UNDER_REVIEW` and recording their `X-User-ID` as `reviewed_by_user_id`. From `UNDER_REVIEW` three doors are open to that reviewer's role. Sending it back moves it `UNDER_REVIEW → CHANGES_REQUESTED` with an optional `note`; the amount stays inside `reserved_payout_cents` throughout, so the funds remain committed while the manager revises. Rejection moves it `UNDER_REVIEW → REJECTED` with an optional `note` and releases the reservation: `reserved_payout_cents` falls by the payout's `amount_cents` and `available_balance_cents` rises by the same figure. `REJECTED` is terminal. Approval moves it `UNDER_REVIEW → APPROVED` and records the acting `X-User-ID` as `approved_by_user_id` — but only if that identifier differs from the recorded `reviewed_by_user_id`. A reviewer who tries to approve the very request they took into review is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Two different reviewers are structurally required for every disbursement.

A payout sent back for changes returns to the campaign manager, who revises and resubmits it with a replacement `amount_cents` and an optional `note`, moving it `CHANGES_REQUESTED → REQUESTED`. Only the manager of the campaign's own organization may resubmit. The resubmitted amount is subject to the same 5000-cent floor (`ERR_PAYOUT_BELOW_MINIMUM`) and must keep the campaign's `available_balance_cents` at or above zero once the reservation is re-computed at the new amount, or it is rejected with `ERR_INSUFFICIENT_CAMPAIGN_BALANCE`. On success the payout's `amount_cents` is replaced with the resubmitted figure, `requested_by_user_id` is set to the acting `X-User-ID`, `reviewed_by_user_id` is cleared so the next review starts clean, and the campaign's `reserved_payout_cents` and `available_balance_cents` are recomputed. The path `CHANGES_REQUESTED → REQUESTED → UNDER_REVIEW → CHANGES_REQUESTED` is a genuine revision cycle a payout may traverse repeatedly.

Release is the platform operator's action, moving an approved payout `APPROVED → RELEASED`. It requires the beneficiary organization's `payout_account_status` to read `VERIFIED`; an `UNVERIFIED` or `SUSPENDED` account blocks the disbursement with `ERR_ORGANIZATION_PAYOUT_UNVERIFIED`. Release stamps `released_at` and moves the amount from `reserved_payout_cents` into `paid_out_cents`; `available_balance_cents` is unchanged by a release, since the money was already committed.

Finally, a released payout that comes back from the bank is voided by the platform operator, moving it `RELEASED → VOIDED` with an optional `reason`. This is a compensating action: `paid_out_cents` falls by the payout's `amount_cents` and `available_balance_cents` rises by the same figure, restoring the conservation identity of §2.10 and returning the money to the campaign's spendable pool. `VOIDED` is terminal.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Operations that create a new resource respond with **201 Created**; every other successful operation — reads, state transitions, and compensating actions — responds with **200 OK**. Request and response payloads are not repeated here; the fields each operation accepts, and the effects each one produces, are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/organizations` | Register a beneficiary nonprofit; the returned id is the acting id for its campaign manager | PlatformAdmin |
| GET | `/api/organizations/{id}` | Read one organization | PlatformAdmin, CampaignManager, FinanceReviewer |
| POST | `/api/organizations/{id}/payout-account` | Set the organization's payout account status | PlatformAdmin |
| POST | `/api/campaigns` | Create a campaign in DRAFT for the acting organization | CampaignManager |
| GET | `/api/campaigns/{id}` | Read one campaign including its recomputed money figures | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/campaigns` | List campaigns, optionally filtered by organization or status | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| POST | `/api/campaigns/{id}/publish` | Move the campaign DRAFT to PUBLISHED | CampaignManager |
| POST | `/api/campaigns/{id}/close` | Move the campaign PUBLISHED to CLOSED and cascade to its events and match pools | CampaignManager |
| GET | `/api/campaigns/{id}/thermometer` | Public progress: credited total, distinct donor count, participant count and floored basis-point progress | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/campaigns/{id}/leaderboard` | Ranked leaderboard for a team or participant scope under the RAW_TOTAL or GOAL_PERCENT variant | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/campaigns/{id}/report` | Operational rollup across gifts, fees, matches, receipts, registrations and awards | PlatformAdmin, CampaignManager, FinanceReviewer |
| POST | `/api/campaigns/{id}/payouts` | Request a disbursement; supersedes any open request and is guarded by optimistic concurrency | CampaignManager |
| POST | `/api/events` | Create a walk/run event under a PUBLISHED campaign | CampaignManager |
| GET | `/api/events/{id}` | Read one event | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/events` | List events, optionally filtered by campaign or status | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| POST | `/api/teams` | Create a fundraising team inside a PUBLISHED campaign | CampaignManager, Participant |
| GET | `/api/teams/{id}` | Read one team with its recomputed credited total | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/teams` | List teams, optionally filtered by campaign, status or captain | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| POST | `/api/teams/{id}/disband` | Disband a team; members are detached and the team leaves the leaderboard | CampaignManager |
| POST | `/api/participants` | Create a personal fundraising page; the returned id is the acting id for that fundraiser | Anonymous, CampaignManager |
| GET | `/api/participants/{id}` | Read one fundraiser page with both credit variants | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/participants` | List fundraiser pages, optionally filtered by campaign, team, recruiter or status | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| POST | `/api/participants/{id}/activate` | Move the fundraiser page PENDING to ACTIVE | Participant, CampaignManager |
| POST | `/api/participants/{id}/withdraw` | Withdraw the fundraiser and cascade-cancel their open registrations | Participant, CampaignManager |
| POST | `/api/registrations` | Reserve an event slot; the fee is stamped at creation | Participant, CampaignManager |
| GET | `/api/registrations/{id}` | Read one registration | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/registrations` | List registrations, optionally filtered by participant, event or status | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| POST | `/api/registrations/{id}/confirm` | Move the registration RESERVED to CONFIRMED; enforces the fundraising minimum unless waived | Participant, CampaignManager |
| POST | `/api/registrations/{id}/cancel` | Cancel a RESERVED or CONFIRMED registration | Participant, CampaignManager |
| POST | `/api/registrations/{id}/check-in` | Record race-day attendance; only valid at or after the event start | CampaignManager |
| POST | `/api/registrations/{id}/no-show` | Mark a confirmed registration as a no-show after the event ends | CampaignManager |
| POST | `/api/donors` | Register a donor; the returned id is the acting id for that donor | Anonymous, PlatformAdmin, CampaignManager |
| GET | `/api/donors/{id}` | Read one donor | PlatformAdmin, CampaignManager, Donor |
| POST | `/api/donations` | Make a gift designated to the campaign, a team or a fundraiser; fees are stamped at creation | Donor, PlatformAdmin |
| GET | `/api/donations/{id}` | Read one gift | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/donations` | List gifts, optionally filtered by campaign, donor, match pool, designation or payment status | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| POST | `/api/donations/{id}/settle` | Settle or fail a pending gift; settlement runs matching, credit, receipt issuance and awards | PlatformAdmin |
| POST | `/api/donations/{id}/refund` | Refund a settled gift and unwind every downstream effect | PlatformAdmin |
| POST | `/api/match-pools` | Create a sponsor matching pool with a half-open window | CampaignManager |
| GET | `/api/match-pools/{id}` | Read one match pool with its remaining balance | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/match-pools` | List match pools, optionally filtered by campaign or status | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| POST | `/api/match-pools/{id}/close` | Close a pool so it stops matching new gifts | CampaignManager |
| POST | `/api/incentive-tiers` | Define an incentive tier fundraisers can earn | CampaignManager |
| GET | `/api/incentive-tiers/{id}` | Read one incentive tier | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/incentive-tiers` | List incentive tiers, optionally filtered by campaign | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/incentive-awards/{id}` | Read one incentive award | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/incentive-awards` | List incentive awards, optionally filtered by participant, tier or status; the only discovery channel for awards | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| POST | `/api/incentive-awards/{id}/fulfill` | Mark an earned award as fulfilled; fulfilled awards survive later refunds | CampaignManager |
| GET | `/api/receipts/{id}` | Read one tax receipt | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| GET | `/api/receipts` | List receipts, optionally filtered by donation, campaign or status; the only discovery channel for receipts | Anonymous, PlatformAdmin, CampaignManager, Participant, Donor, FinanceReviewer |
| POST | `/api/receipts/{id}/void` | Void an issued receipt | CampaignManager, PlatformAdmin |
| POST | `/api/receipts/{id}/reissue` | Re-issue a voided receipt under its original receipt number | CampaignManager, PlatformAdmin |
| GET | `/api/payouts/{id}` | Read one payout request | PlatformAdmin, CampaignManager, FinanceReviewer |
| GET | `/api/payouts` | List payouts, optionally filtered by campaign or status | PlatformAdmin, CampaignManager, FinanceReviewer |
| POST | `/api/payouts/{id}/review` | Take the payout into review; records the reviewing finance reviewer | FinanceReviewer |
| POST | `/api/payouts/{id}/request-changes` | Send the payout back to the campaign manager for revision | FinanceReviewer |
| POST | `/api/payouts/{id}/resubmit` | Revise and resubmit a payout that was sent back | CampaignManager |
| POST | `/api/payouts/{id}/approve` | Approve a payout under review; the approver must differ from the reviewer | FinanceReviewer |
| POST | `/api/payouts/{id}/reject` | Reject a payout under review and release its reservation | FinanceReviewer |
| POST | `/api/payouts/{id}/release` | Disburse an approved payout; requires a VERIFIED organization payout account | PlatformAdmin |
| POST | `/api/payouts/{id}/void` | Compensating action for a released payout; restores the campaign's available balance | PlatformAdmin |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ORGANIZATION_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_TEAM_NOT_FOUND` | 404 |
| `ERR_PARTICIPANT_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_DONOR_NOT_FOUND` | 404 |
| `ERR_DONATION_NOT_FOUND` | 404 |
| `ERR_MATCH_POOL_NOT_FOUND` | 404 |
| `ERR_TIER_NOT_FOUND` | 404 |
| `ERR_AWARD_NOT_FOUND` | 404 |
| `ERR_RECEIPT_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DONATION_NOT_REFUNDABLE` | 409 |
| `ERR_REFUND_WINDOW_EXPIRED` | 422 |
| `ERR_CAMPAIGN_NOT_PUBLISHED` | 409 |
| `ERR_PARTICIPANT_NOT_ACTIVE` | 409 |
| `ERR_DESIGNATION_UNRESOLVABLE` | 422 |
| `ERR_EVENT_CAMPAIGN_MISMATCH` | 422 |
| `ERR_TEAM_CAMPAIGN_MISMATCH` | 422 |
| `ERR_SELF_RECRUIT` | 422 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_REGISTRATION_TIME_CONFLICT` | 409 |
| `ERR_EVENT_AT_CAPACITY` | 422 |
| `ERR_MATCH_WINDOW_OVERLAP` | 409 |
| `ERR_FUNDRAISING_MINIMUM_NOT_MET` | 422 |
| `ERR_PAYOUT_BELOW_MINIMUM` | 422 |
| `ERR_INSUFFICIENT_CAMPAIGN_BALANCE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ORGANIZATION_PAYOUT_UNVERIFIED` | 409 |
| `ERR_STALE_CAMPAIGN_VERSION` | 412 |
