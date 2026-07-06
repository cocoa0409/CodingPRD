# Petition & Civic Advocacy API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Petition & Civic Advocacy API, a crowdsourced campaigning platform in the spirit of Change.org. Members author petitions that name a decision-maker, rally verified supporters through a token-confirmed signing flow, and — once they have both real support and a face-to-face delivery on the record — declare victory or withdraw. Around that spine sit a fundraising layer (campaigns, donations, and paid promotional placement), a public discussion layer (moderated comments and author updates), and an operational layer that maps petitions to real elected officials through a representative directory and schedules delivery meetings with their offices.

The platform is deliberately posture-driven: a petition's moderation standing gates whether it can accrue signatures, be commented upon, or be promoted, and a web of derived tallies (verified-signature counts, funds raised, milestone ladders) must stay reconciled with the underlying facts at all times. Because money and civic credibility are both at stake, the system distinguishes carefully between *provisional* figures (pending signatures, pledged-but-uncaptured donations) and *official* figures (verified signatures, net settled funds), and it applies compensating reversals whenever a signature is revoked, a donation refunded, or a petition closed. This specification defines every entity, state transition, calculation, validation, and access-control rule that a conforming implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than open self-registration and public reads must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the call is made. When either header is missing, or `X-User-Role` is not one of the declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `Guest`, `Member`, `Moderator`, and `Admin`.

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `User`. Ownership checks on any resource that references a `User` compare the resource's owner foreign key — `author_user_id` on a `Petition` or `Comment`, `signer_user_id` on a `Signature`, `donor_user_id` on a `Donation`, or `purchaser_user_id` on a `Promotion` — to `X-User-ID`. A `Member` acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `Guest`, `X-User-ID` is an opaque visitor identifier not tied to any persisted entity; a `Guest` may only self-register a new account and read public resources.
- When `X-User-Role` is `Moderator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; a moderator's authority is role-derived, not ownership-derived.
- When `X-User-Role` is `Admin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`.

`Guest` is the only role that may register an account and is otherwise limited to reads. `Member` owns and drives all content: authoring petitions, signing, commenting, donating, promoting, and scheduling deliveries. `Moderator` owns content governance: reviewing petitions, moderating comments, revoking fraudulent signatures, and suspending or reactivating campaigns. `Admin` owns platform operations: the representative directory, target reachability, payment settlement and refunds, meeting confirmation, and the logical clock. Advancing a delivery meeting is shared: a `Member` who authored the petition and an `Admin` can both drive meeting transitions, subject to the per-transition rules in §3.

Anyone may self-register a `User` account by supplying a login `email` (unique, compared case-insensitively), a `full_name` display name, and a `jurisdiction` civic district code that is later matched against a petition's `eligible_jurisdiction` when the user signs. Each `User` also carries an advisory `role_hint` field, which defaults to `MEMBER`; this is a self-declared hint only and never a source of authorization — the effective role is always taken from `X-User-Role`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. Every list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` is the count of all matching items before the limit/offset window is applied and `has_more` is true when items remain beyond the returned page.

### 2.4. Common Resource Properties

Every top-level resource in this system — `User`, `Petition`, `Target`, `Representative`, `Signature`, `Comment`, `Campaign`, `Donation`, `Promotion`, and `DeliveryMeeting` — carries a common set of server-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that starts at its initial value on creation and increments by exactly 1 on every mutation of the resource. All ten entities in this system use the full common-field set; none omit `updated_at` or `version`.

Because reconciliation of a derived field is itself a mutation, any recompute that changes a stored derived value on an entity — for example a change to a `Petition`'s `verified_signature_count` or a `Campaign`'s `funds_raised_cents` — refreshes that entity's `updated_at` and increments its `version`.

### 2.5. Path Resolution and Validation Ordering

When a request path names a resource by `id`, that resource must exist; a missing resource yields the entity-specific not-found error — `ERR_USER_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_TARGET_NOT_FOUND`, `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_SIGNATURE_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND`, or `ERR_MEETING_NOT_FOUND` — each with HTTP 404. When a path carries more than one identifier, identifiers are resolved strictly left-to-right, and the first one that does not resolve determines the 404 returned.

Validation across the whole API follows one fixed priority order, and the earliest failing check is the one reported. The order is: (1) authentication of the `X-User-Role`/`X-User-ID` headers (`ERR_UNAUTHENTICATED`, 401); (2) role authorization for the operation (`ERR_UNAUTHORIZED`, 403); (3) existence of every path-referenced resource (the entity-specific 404); (4) resource ownership for member-owned mutations (`ERR_NOT_RESOURCE_OWNER`, 403); (5) well-formedness of the request body — required fields present, enums within their allowed set, integers within their declared bounds, and every `window_end` strictly greater than its `window_start` (`ERR_VALIDATION`, 422); (6) optimistic-concurrency version match (`ERR_STALE_PETITION_VERSION`, 412); (7) the generic legal-state check for the requested transition (`ERR_INVALID_STATE`, 409); and then the domain-specific business checks described throughout §3. Ownership (step 4) is enforced for petition edit, submit, close, target-setting, and author updates; signature verification; promotion cancellation; and meeting delivery.

### 2.6. Optimistic Concurrency on Decision-Maker Changes

Setting or replacing a petition's decision-maker is guarded by optimistic concurrency against the parent `Petition`. A request that creates a new `Target` for a petition must carry `expected_petition_version` holding the client's last observed `Petition` `version`. If another writer has advanced the petition's `version` since the client last read it — for instance by already replacing the decision-maker and superseding the prior one — the client's view is stale, and the request is rejected with `ERR_STALE_PETITION_VERSION` (HTTP 412). Editing a petition's fields is guarded the same way: that request also carries `expected_petition_version`, and a mismatch with the petition's current `version` is likewise rejected with `ERR_STALE_PETITION_VERSION` (HTTP 412). No other endpoint takes a version field, and endpoints without one perform no concurrency check.

### 2.7. Derived-Figure Reconciliation and Dual Variants

Several stored figures are *derived*: they are maintained by the server as underlying facts change rather than written directly by clients, and the system keeps them continuously reconciled. Two domains carry a deliberate two-figure design.

On a petition, the **official** figure is `verified_signature_count`, the number of signatures in `VERIFIED` status; it drives the goal, the milestone ladder, victory eligibility, and the public headline number. The **provisional** figure adds pending confirmations: `pending_signature_count` is the number of signatures still in `PENDING_VERIFICATION`, and a signature that has been created but not yet confirmed raises the provisional picture without affecting the official count. Signatures in `REJECTED` or `REVOKED` status are excluded from both counts.

On a campaign, the **provisional** figure is `gross_pledged_cents`, the sum of `amount_cents` across every donation whose status is `PENDING` or `SETTLED`, taken at full gross with no fee deducted; it powers the optimistic progress bar. The **official** figure is `funds_raised_cents`, the withdrawable balance: the sum of `net_to_campaign_cents` over `SETTLED` donations minus the sum of `net_to_campaign_cents` over `REFUNDED` donations. A donation that is only pledged (still `PENDING`) inflates the gross figure but contributes nothing to the official raised total until it settles.

### 2.8. Monetary and Count Precision

All money is represented as integer cents; there are no fractional cents in stored values or responses. Signature and comment tallies are exact integer counts. Where a calculation produces a non-integer intermediate — the platform fee on a donation, or a promotion's clamped subtotal — the result is rounded to a whole number of cents using round-half-up (a value exactly halfway between two integers rounds up to the larger). The precise point at which rounding is applied is pinned per calculation and is stated with each formula in §3; implementations must round exactly where indicated, because rounding earlier or later shifts the final cents.

### 2.9. The Logical Clock and Time-Derived Promotion States

The platform runs on a server-controlled logical clock rather than wall-clock time. Before any clock is set, the clock reads exactly `2026-03-01T00:00:00Z`; it never falls back to real wall-clock time. An administrator may advance the clock by supplying a `to_iso8601` instant. All time-dependent behavior — chiefly the promotion feature window — is evaluated against this logical clock. A promotion's live status is derived from its window relative to the current clock and is observed on read and on operations: while the clock is before `window_start` the promotion is `SCHEDULED`; once the clock reaches or passes `window_start` it is `ACTIVE`; once the clock reaches or passes `window_end` it is `COMPLETED`.

## 3. Business Logic & Workflows

### 3.1. Authoring and Moderating a Petition

A `Member` opens a campaign by creating a `Petition`, supplying its `title`, `summary`, `body`, `category`, and `goal`, and optionally an `eligible_jurisdiction`. The `category` must be one of `ENVIRONMENT`, `POLITICS`, `HEALTH`, `EDUCATION`, or `OTHER`, and the `goal` — the target number of verified signatures — must be at least 1. On creation the petition's `author_user_id` is set to the acting `X-User-ID`, its `status` begins at `DRAFT`, and its `moderation_status` begins at `PENDING`. The `eligible_jurisdiction` defaults to null, meaning open to all signers; when set to a civic district code it restricts who may sign (see §3.3). While a petition remains in `DRAFT` or `CHANGES_REQUESTED`, its author may revise `title`, `summary`, `body`, `goal`, or `eligible_jurisdiction`; each successful edit increments the petition's `version` by 1 and, per §2.6, requires a matching `expected_petition_version`.

Before a petition can enter review it must name a decision-maker: submitting a petition for review advances it from `DRAFT` to `UNDER_REVIEW`, and is permitted only when the caller is the petition author and the petition has an `ACTIVE` `Target`. The revision loop is cyclic: a petition that a moderator sent back to `CHANGES_REQUESTED` can be resubmitted by its author, again moving to `UNDER_REVIEW`. Submitting from any other state is not a legal transition and is refused with `ERR_INVALID_STATE`.

A `Moderator` renders one of three decisions on a petition under review, supplying a `decision` of `APPROVE`, `REQUEST_CHANGES`, or `REMOVE`. Approving it moves the petition from `UNDER_REVIEW` to `PUBLISHED`; as side effects the `moderation_status` becomes `APPROVED`, `published_at` is set to the current clock instant but only if it was previously null (so a petition removed and somehow re-published keeps its original publication time), and the milestone ladder is fixed at this moment (§3.3). Requesting changes moves it from `UNDER_REVIEW` to `CHANGES_REQUESTED` with no further effect. Removing it moves it from `UNDER_REVIEW` to `REMOVED` and sets `moderation_status` to `BLOCKED`. A moderator may also remove an already-`PUBLISHED` petition, moving it from `PUBLISHED` to `REMOVED` and likewise setting `moderation_status` to `BLOCKED`. A moderation decision may carry an optional `note`. `REMOVED`, `CLOSED_VICTORY`, and `CLOSED_WITHDRAWN` are terminal petition states.

### 3.2. Decision-Makers, Targets, and the Representative Directory

An `Admin` curates a directory of elected officials. Each `Representative` entry records the official's `full_name`, the `office` held, the `jurisdiction` district code they serve, and an official `contact_email`. Anyone may look up representatives, filtering by `jurisdiction` or `office`, which is how a campaigner finds the right person to petition.

A petition's decision-maker is expressed as a `Target`. When the author sets or replaces the target, they provide the decision-maker's `name`, office `title`, and governing `office`, and may include a `representative_id` linking the target to a directory entry. The new target references its petition through `petition_id` and begins in `ACTIVE` status. Setting a replacement target automatically supersedes the prior one: the previously `ACTIVE` `Target` moves from `ACTIVE` to `SUPERSEDED`, and the petition's `version` increments by 1. Because this write is concurrency-guarded, it carries `expected_petition_version` and is rejected with `ERR_STALE_PETITION_VERSION` when that value no longer equals the petition's current `version` (§2.6).

An administrator may mark a target unreachable, moving it from `ACTIVE` to `UNREACHABLE`. This triggers the **target-unreachable cascade**: every `DeliveryMeeting` for that target still in `REQUESTED` or `CONFIRMED` is moved to `CANCELLED`. A meeting that had already reached `DELIVERED` is terminal and is left untouched, so the petition's `delivered_meeting_count` is unchanged by deactivation — cancelled, never-delivered meetings never contributed to that count in the first place. `SUPERSEDED` and `UNREACHABLE` are terminal target states.

### 3.3. Collecting and Verifying Signatures

Signing is the heart of the platform, and it is a two-step, token-confirmed process gated on publication. A `Member` signs a petition, optionally attaching a `public_comment` shown alongside their name. Signing is permitted only while the parent petition's `status` is `PUBLISHED`; an attempt to sign a petition in any other state is rejected with `ERR_PETITION_NOT_PUBLISHED`. If the petition carries an `eligible_jurisdiction`, the signer's `User.jurisdiction` must equal it exactly, or the request is refused with `ERR_JURISDICTION_MISMATCH`. A user may hold at most one non-terminal signature — one in `PENDING_VERIFICATION` or `VERIFIED` — per petition; a second attempt while such a signature stands is rejected with `ERR_DUPLICATE_SIGNATURE`. A successful sign creates a `Signature` whose `petition_id` names the petition and whose `signer_user_id` is set to the acting `X-User-ID`, issues a server-minted `verification_token`, sets the signature's `status` to `PENDING_VERIFICATION`, and increases the petition's `pending_signature_count` by 1.

Confirmation moves a signature from `PENDING_VERIFICATION` to `VERIFIED`. The signer submits the `verification_token`; it must equal the token issued for that signature or the request fails with `ERR_INVALID_VERIFICATION_TOKEN`, and the parent petition must still be `PUBLISHED` or the request fails with `ERR_PETITION_NOT_PUBLISHED`. On success the petition's `verified_signature_count` increases by 1 and its `pending_signature_count` decreases by 1, and the goal and milestone figures are recomputed as described below.

A `Moderator` may act against fraud by revoking a signature. Revoking a signature that is still `PENDING_VERIFICATION` moves it to `REJECTED` and decreases the petition's `pending_signature_count` by 1; a `reason` may be supplied. Revoking a signature that is already `VERIFIED` moves it to `REVOKED` and triggers the **signature-revoke cascade**: the petition's `verified_signature_count` is decreased by 1, and that lower count is then fed back through the goal and milestone recomputation. `REJECTED` and `REVOKED` are terminal signature states. Petition withdrawal also rejects signatures in bulk, as described in §3.8.

The **milestone ladder** is fixed once, at first publication, from the petition's `goal`. The candidate thresholds are the default first milestone of 100 signatures, the goal rounded up to the next whole number when halved, and the goal itself; formally the three candidates are 100, the ceiling of `goal` divided by 2, and `goal`. From these candidates the system keeps only those that are at least 1 and at most the `goal`, removes duplicates, sorts them ascending, and stores the result as `milestone_thresholds`. Thereafter, on every verify or revoke, `milestones_reached` is recomputed as the subset of `milestone_thresholds` whose threshold is less than or equal to the current `verified_signature_count`, and `goal_reached` is set true exactly when `verified_signature_count` is greater than or equal to `goal`. The official `verified_signature_count` is what feeds these; the provisional total that also counts `PENDING_VERIFICATION` signatures is a dashboard figure only and never advances a milestone or the goal.

### 3.4. Public Comments and Author Updates

Discussion and progress reporting share one entity, distinguished by `comment_type`. A `Member` posts to a petition by supplying `body` and a `comment_type` of either `COMMENT` or `UPDATE`; the created record's `author_user_id` is the acting `X-User-ID` and it references the petition by `petition_id`. A `COMMENT` is signer discussion and enters moderation at `PENDING`. An `UPDATE` is an author progress report: it may be posted only by the petition's author, is auto-approved to `APPROVED` on creation, and is eligible to be delivered to signers.

A `Moderator` moderates a `COMMENT` — and only a record whose `comment_type` is `COMMENT`, in a state and type eligible for the requested decision, or the request is refused with `ERR_CONTENT_NOT_MODERATABLE`. Approving a pending comment moves it from `PENDING` to `APPROVED` and increases the petition's `approved_comment_count` by 1. Rejecting a pending comment moves it from `PENDING` to `REJECTED` with no count effect. Any `Member` may flag an approved comment they find objectionable, moving it from `APPROVED` to `FLAGGED` and decreasing the petition's `approved_comment_count` by 1. A moderator then resolves the flag in one of two divergent ways: dismissing the flag restores the comment, moving it from `FLAGGED` back to `APPROVED` and increasing `approved_comment_count` by 1 again; removing it moves it from `FLAGGED` to `REMOVED` and does **not** change the count, precisely because the count was already decremented when the comment was flagged. `PENDING`, `APPROVED`, `REJECTED`, `FLAGGED`, and `REMOVED` are the comment lifecycle states; `REJECTED` and `REMOVED` are terminal. `approved_comment_count` reflects only records with `comment_type` `COMMENT` in `APPROVED` status.

The petition author may mark an approved `UPDATE` as delivered to signers, which sets the record's `delivered` flag to true. Delivery applies to `UPDATE`-type records only and may be performed only by the author.

### 3.5. Scheduling and Recording Delivery Meetings

Delivering a petition to its decision-maker is tracked as a `DeliveryMeeting`, and a real, recorded delivery is a precondition of victory. A `Member` schedules a meeting by naming the `petition_id`, the `target_id` of the decision-maker, and a `window_start` and `window_end`, where `window_end` must be strictly after `window_start`. The window is half-open — `[window_start, window_end)` — so the end instant is excluded. The referenced `Target` must be `ACTIVE` at scheduling time, or the request is refused with `ERR_TARGET_UNREACHABLE`. A target holds at most one live meeting at a time: consecutive meetings on the same target must leave a gap of at least 15 minutes, measured between the earlier meeting's `window_end` and the later meeting's `window_start`. A requested window that falls within 15 minutes of an existing `REQUESTED` or `CONFIRMED` meeting on the same target is rejected with `ERR_MEETING_CONFLICT`; because windows are half-open, two windows that merely touch at an endpoint do not themselves overlap, but the 15-minute buffer between them must still be respected. A new meeting begins in `REQUESTED`.

Meetings advance by a supplied `to_status`. An `Admin` confirms a meeting, moving it from `REQUESTED` to `CONFIRMED`, which requires the target still be `ACTIVE` (otherwise `ERR_TARGET_UNREACHABLE`). The petition author records the delivery, moving a meeting from `CONFIRMED` to `DELIVERED`; this too requires the target be `ACTIVE`, is restricted to the petition author, and increases the petition's `delivered_meeting_count` by 1 — the fact that unlocks victory closure. Either the petition-author `Member` or an `Admin` may cancel a meeting, moving it from `REQUESTED` to `CANCELLED` or from `CONFIRMED` to `CANCELLED`; the target-unreachable cascade of §3.2 drives these same cancellations automatically. `DELIVERED` and `CANCELLED` are terminal meeting states, and any transition not enumerated here is refused with `ERR_INVALID_STATE`.

### 3.6. Fundraising: Campaigns, Donations, and the Fee Split

A petition may run a single fundraising `Campaign`, created by the author with a `goal_cents` target that must be at least 0; the campaign references its petition by `petition_id` and starts `ACTIVE`. A `Moderator` governs a campaign by supplying an `action` of `SUSPEND`, which moves it from `ACTIVE` to `SUSPENDED`, or `REACTIVATE`, which moves it from `SUSPENDED` back to `ACTIVE`. `CLOSED` is a terminal campaign state reached only through petition closure (§3.8).

A `Member` donates to a campaign with an `amount_cents` of at least 100. Donations are accepted only while the campaign's `status` is `ACTIVE`; a donation attempted against a `SUSPENDED` or `CLOSED` campaign is rejected with `ERR_CAMPAIGN_SUSPENDED`. A successful donation creates a record whose `campaign_id` names the campaign and whose `donor_user_id` is the acting `X-User-ID`, entering `PENDING` status, and refreshes the campaign's provisional `gross_pledged_cents`.

Payment transitions are administrator-driven via a supplied `to_status`. Settling a donation moves it from `PENDING` to `SETTLED`, which is permitted only when the campaign is not `CLOSED`, and computes the fee split. The **fee split** is pinned per donation: the `platform_fee_cents` is the donation's `amount_cents` multiplied by the platform fee rate of 2.9 percent (0.029), rounded half-up to whole cents, plus a fixed fee of 30 cents; the `net_to_campaign_cents` is the `amount_cents` minus that `platform_fee_cents`. On settlement the campaign's official `funds_raised_cents` increases by exactly this donation's `net_to_campaign_cents`. The roll-up order is pinned: the campaign total is the sum of the already-rounded per-donation nets, not the fee applied once to a summed gross — rounding each donation's fee first and then summing yields different cents than summing first and rounding once, and the former is required. Failing a donation moves it from `PENDING` to `FAILED` with no effect on funds. Refunding a `SETTLED` donation moves it to `REFUNDED` and applies the compensating reversal: the campaign's `funds_raised_cents` decreases by exactly that donation's `net_to_campaign_cents`. `SETTLED`, `REFUNDED`, and `FAILED` are terminal donation states.

### 3.7. Promoting a Petition for Featured Placement

A `Member` may purchase featured placement for a petition. Promotion is a safety-gated privilege: the petition must be promotable, meaning its `moderation_status` is `APPROVED` and its `status` is `PUBLISHED`, or the purchase is rejected with `ERR_PETITION_NOT_PROMOTABLE`. The purchaser supplies the `petition_id`, a `placement_tier` of `STANDARD`, `PREMIUM`, or `SPOTLIGHT`, and a `window_start` and `window_end`, where `window_end` must be strictly after `window_start`. On creation the promotion's `category` is copied from the petition's `category`, the `purchaser_user_id` is set to the acting `X-User-ID`, the price is computed, and the promotion enters `SCHEDULED`.

Featured slots are capacity-limited per category to 2 concurrent placements. Overlap is judged on the half-open window `[window_start, window_end)`, so a window that abuts another exactly at a shared endpoint does not overlap it. The purchase is rejected with `ERR_PROMO_SLOT_UNAVAILABLE` only when 2 or more other promotions in the same `category`, each in `SCHEDULED` or `ACTIVE` status, already overlap the requested window.

The **promotion price** combines tier, duration, and category demand with a clamp. First, `duration_days` is the length of the window in whole days, computed as the ceiling of the elapsed time — the difference between `window_end` and `window_start`, in seconds, divided by 86400 seconds per day — rounded up to the next whole day. A raw amount is then the tier's base rate multiplied by `duration_days` and multiplied by the category's demand multiplier. The per-tier base rates are 5000 cents for `STANDARD`, 12000 cents for `PREMIUM`, and 25000 cents for `SPOTLIGHT`. The category demand multipliers are 1.5 for `ENVIRONMENT`, 2.0 for `POLITICS`, 1.2 for `HEALTH`, 1.0 for `EDUCATION`, and 1.0 for `OTHER`. The raw amount is then clamped to lie within a floor of 5000 cents and a ceiling of 200000 cents: any value below the floor becomes the floor, and any value above the ceiling becomes the ceiling. The clamped subtotal is rounded half-up to whole cents, and only then is a flat listing fee of 1500 cents added to produce `price_cents`. The evaluation order is pinned — the clamp is applied before the listing fee is added — so the listing fee is never clamped away.

Before a promotion's window opens, its purchaser may cancel it, moving it from `SCHEDULED` to `CANCELLED` for a refund; cancellation is restricted to the purchaser and is permitted only while the current clock is before `window_start`. A promotion that is not `SCHEDULED`, or whose window has already started, cannot be cancelled and the attempt is rejected with `ERR_PROMO_NOT_CANCELLABLE`. As described in §2.9, the platform itself advances a promotion from `SCHEDULED` to `ACTIVE` when the clock reaches `window_start` and from `ACTIVE` to `COMPLETED` when the clock reaches `window_end`. `CANCELLED` and `COMPLETED` are terminal promotion states.

### 3.8. Closing a Petition: Victory, Withdrawal, and the Refund Cascade

Only the petition author may close a `PUBLISHED` petition, and the `outcome` supplied — either `VICTORY` or `WITHDRAWN` — determines both the terminal state and the side effects. Declaring **victory** moves the petition from `PUBLISHED` to `CLOSED_VICTORY`, but only when the campaign has produced real, delivered support: the petition must have a `verified_signature_count` greater than 0 — checked first, and if it fails the closure is rejected with `ERR_NO_VERIFIED_SIGNATURES` — and a `delivered_meeting_count` of at least 1 — checked second, rejected with `ERR_NO_DELIVERY`. Declaring **withdrawal** moves the petition from `PUBLISHED` to `CLOSED_WITHDRAWN` with no support preconditions, and as a side effect rejects every signature still awaiting confirmation: all of the petition's `PENDING_VERIFICATION` signatures are moved to `REJECTED`.

Either closure outcome triggers the **closure-refund cascade** against the petition's campaign, if one exists and is not already `CLOSED`. The first link moves that `Campaign` — whether it was `ACTIVE` or `SUSPENDED` — to `CLOSED`. The second link, fired by the campaign closing, moves every `PENDING` `Donation` on that campaign to `REFUNDED`. The third link reconciles the campaign's `funds_raised_cents`: a donation that was only pending never contributed settled net to the official total, so voiding it leaves `funds_raised_cents` unchanged, while any donation refunded from a settled state reverses its own `net_to_campaign_cents` exactly. The net effect is that closing a petition conserves the official raised balance except for the exact, intended reversals — pending pledges evaporate with no accounting impact, and previously settled money that is refunded is backed out cent-for-cent.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, or that carry no resource body, return `200 OK`. Reads return `200 OK`. The request and response payloads for each operation are described in the §3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/users` | Register a user account | Guest |
| GET | `/users/{id}` | Get a user | Guest, Member, Moderator, Admin |
| POST | `/petitions` | Create a petition (DRAFT) | Member |
| GET | `/petitions/{id}` | Get a petition | Guest, Member, Moderator, Admin |
| GET | `/petitions` | List/filter petitions | Guest, Member, Moderator, Admin |
| PATCH | `/petitions/{id}` | Edit a petition (DRAFT or CHANGES_REQUESTED only) | Member |
| POST | `/petitions/{id}/submit` | Submit a petition for review | Member |
| POST | `/petitions/{id}/moderate` | Moderator decision on a petition | Moderator |
| POST | `/petitions/{id}/close` | Author closes a petition (VICTORY or WITHDRAWN) | Member |
| POST | `/petitions/{id}/target` | Set/replace the petition's decision-maker | Member |
| GET | `/targets/{id}` | Get a target | Guest, Member, Moderator, Admin |
| GET | `/targets` | List/filter targets | Guest, Member, Moderator, Admin |
| POST | `/targets/{id}/deactivate` | Mark a target UNREACHABLE | Admin |
| POST | `/representatives` | Add a directory entry | Admin |
| GET | `/representatives/{id}` | Get a representative | Guest, Member, Moderator, Admin |
| GET | `/representatives` | Look up representatives by jurisdiction/office | Guest, Member, Moderator, Admin |
| POST | `/petitions/{id}/signatures` | Sign a petition | Member |
| GET | `/signatures/{id}` | Get a signature | Guest, Member, Moderator, Admin |
| GET | `/signatures` | List/filter signatures | Guest, Member, Moderator, Admin |
| POST | `/signatures/{id}/verify` | Confirm a signature with its token | Member |
| POST | `/signatures/{id}/revoke` | Revoke/reject a signature | Moderator |
| POST | `/petitions/{id}/comments` | Post a comment or author update | Member |
| GET | `/comments/{id}` | Get a comment/update | Guest, Member, Moderator, Admin |
| GET | `/comments` | List/filter comments/updates | Guest, Member, Moderator, Admin |
| POST | `/comments/{id}/moderate` | Moderate a comment | Moderator |
| POST | `/comments/{id}/flag` | Flag an approved comment | Member |
| POST | `/comments/{id}/deliver` | Mark an approved update delivered | Member |
| POST | `/petitions/{id}/campaign` | Create the petition's fundraising campaign | Member |
| GET | `/campaigns/{id}` | Get a campaign | Guest, Member, Moderator, Admin |
| GET | `/campaigns` | List/filter campaigns | Guest, Member, Moderator, Admin |
| POST | `/campaigns/{id}/moderate` | Suspend or reactivate a campaign | Moderator |
| POST | `/campaigns/{id}/donations` | Donate to a campaign | Member |
| GET | `/donations/{id}` | Get a donation | Guest, Member, Moderator, Admin |
| GET | `/donations` | List/filter donations | Guest, Member, Moderator, Admin |
| POST | `/donations/{id}/transition` | Payment transition (SETTLED/FAILED/REFUNDED) | Admin |
| POST | `/promotions` | Buy a featured promotion slot | Member |
| GET | `/promotions/{id}` | Get a promotion | Guest, Member, Moderator, Admin |
| GET | `/promotions` | List/filter promotions | Guest, Member, Moderator, Admin |
| POST | `/promotions/{id}/cancel` | Cancel a SCHEDULED promotion | Member |
| POST | `/delivery-meetings` | Schedule a delivery meeting | Member |
| GET | `/delivery-meetings/{id}` | Get a delivery meeting | Guest, Member, Moderator, Admin |
| GET | `/delivery-meetings` | List/filter delivery meetings | Guest, Member, Moderator, Admin |
| POST | `/delivery-meetings/{id}/transition` | Advance a meeting (CONFIRMED/DELIVERED/CANCELLED) | Member, Admin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_USER_NOT_FOUND` | 404 |
| `ERR_PETITION_NOT_FOUND` | 404 |
| `ERR_TARGET_NOT_FOUND` | 404 |
| `ERR_REPRESENTATIVE_NOT_FOUND` | 404 |
| `ERR_SIGNATURE_NOT_FOUND` | 404 |
| `ERR_COMMENT_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_DONATION_NOT_FOUND` | 404 |
| `ERR_PROMOTION_NOT_FOUND` | 404 |
| `ERR_MEETING_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_STALE_PETITION_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PETITION_NOT_PUBLISHED` | 409 |
| `ERR_PETITION_NOT_PROMOTABLE` | 403 |
| `ERR_CONTENT_NOT_MODERATABLE` | 409 |
| `ERR_JURISDICTION_MISMATCH` | 422 |
| `ERR_INVALID_VERIFICATION_TOKEN` | 422 |
| `ERR_PROMO_SLOT_UNAVAILABLE` | 409 |
| `ERR_MEETING_CONFLICT` | 409 |
| `ERR_TARGET_UNREACHABLE` | 409 |
| `ERR_DUPLICATE_SIGNATURE` | 409 |
| `ERR_NO_VERIFIED_SIGNATURES` | 422 |
| `ERR_NO_DELIVERY` | 422 |
| `ERR_CAMPAIGN_SUSPENDED` | 409 |
| `ERR_PROMO_NOT_CANCELLABLE` | 409 |
