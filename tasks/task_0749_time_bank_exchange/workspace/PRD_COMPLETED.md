# Time-Bank Exchange API — Product Requirements Document

## 1. Introduction

The Time-Bank Exchange is a mutual-aid platform in which members trade skilled hours instead of money. A gardener helps a neighbor mulch a bed, an accountant coaches a small-business owner through their first quarterly filing, a retired teacher tutors a middle-schooler through fractions — and each transaction posts an equal number of minutes on both sides of a communal ledger. The unit of account is one minute of contributed time; every member's balance is the running sum of the minutes they have earned less the minutes they have spent or redeemed for pooled rewards.

Because the ledger is the community's shared measure of trust, its integrity has to be defensible at both the individual and the aggregate level. A member's balance must never be spent twice, a settlement must never post fewer or more minutes than were actually delivered, a disputed session must be reconcilable minute-for-minute, and a monthly impact report must sum to the same total whether it is computed at midnight on the last day of the month or on the fifth of the following month. This document specifies the API and the workflows that stand behind those guarantees — the member lifecycle, the offer/request/exchange matching surface, the peer verification protocol that governs trust tiers, the group-project scaffolding on top of one-to-one exchanges, the redemption path, dispute resolution, and the monthly impact reporting pipeline.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every authenticated request must carry two HTTP headers: `X-User-ID`, which identifies the caller, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing or syntactically malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the header is well-formed but the declared role is not authorized for the endpoint, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

Four roles participate in the system:

- `Anonymous` is an unauthenticated caller and identifies opaquely: no persistent entity backs the identity, and the only operation available is member registration.
- `Member` is the standard participant. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks on any resource that references a `Member` compare the resource's owning member foreign-key field to `X-User-ID`.
- `ProjectOrganizer` is a member acting in an organizing capacity. When `X-User-Role` is `ProjectOrganizer`, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks against `GroupProject.organizer_member_id` compare that field to `X-User-ID`.
- `PlatformAdmin` operates the logical clock, fulfils and voids redemptions, resolves disputes, and generates impact reports. `X-User-ID` for a `PlatformAdmin` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `generated_by_user_id` on an impact report — but does not compare it against any `Member.id`.

A missing owner-match (a `Member` acting on a resource whose owning member does not equal `X-User-ID`, or on an exchange in which the requester and provider would resolve to the same member) is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

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

List endpoints accept a `limit` and an `offset` query parameter. The default `limit` is 10, the minimum accepted value is 1, and the maximum is 100; the default `offset` is 0. List results are returned in ascending `created_at` order — never by identifier and never in insertion order. The pagination echo in the response `meta` block carries `limit`, `offset`, `total_count`, and `has_more`; `total_count` is the size of the filtered result set before the window is applied, and `has_more` is true whenever `offset + limit` is smaller than `total_count`.

### 2.4. Common Resource Properties and Identifier Conventions

Every persisted resource is assigned a server-minted `id` that is a UUID string carrying no type prefix; identifiers are opaque and never used as a tiebreak in ordering, ranking, or auto-close logic. Every resource that participates in mutation flows carries `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, plus an integer `version` that starts at 1 on creation and is incremented on every mutation that alters the resource. `LedgerEntry` rows are the sole exception: because the ledger is strictly append-only, a `LedgerEntry` carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field, and the server never rewrites a posted entry.

Timestamps that describe application-level moments — `earliest_start_utc`, `latest_start_utc`, `scheduled_start_utc`, `settled_at_utc`, `fulfilled_at_utc`, `check_in_utc`, `shift_start_utc`, `window_start_utc`, `window_end_utc`, `posted_at` — are always ISO 8601 UTC with three fractional digits and are evaluated against the platform's logical clock (see §2.5), never the host's wall clock. `report_month` is a `YYYY-MM` calendar-month string.

Enum-valued fields carry a fixed vocabulary. `Member.trust_tier` is one of `UNVERIFIED`, `BASIC`, `TRUSTED`, or `ANCHOR`, ordered strictly ascending. `SkillOffer.status` is one of `ACTIVE`, `PAUSED`, or `ARCHIVED`. `SkillRequest.status` is one of `OPEN`, `MATCHED`, `EXPIRED`, `CANCELLED`, or `CLOSED`. `Exchange.status` is one of `SCHEDULED`, `DELIVERED`, `DISPUTED`, `SETTLED`, or `CANCELLED`. `Redemption.status` is one of `REQUESTED`, `FULFILLED`, or `VOIDED`. `VerificationCredential.status` is one of `SUBMITTED`, `REVISION_REQUESTED`, `VERIFIED`, or `REJECTED`, and its `credential_type` is one of `ID_CHECK`, `SKILL_ATTEST`, or `REFERENCE_ATTEST`. `GroupProject.aggregate_state` is one of `PLANNING`, `OPEN`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`. `ProjectShift.status` is one of `OPEN`, `FILLED`, `COMPLETED`, or `CANCELLED`. `ShiftAssignment.status` is one of `CONFIRMED`, `CHECKED_IN`, `COMPLETED`, `NO_SHOW`, or `CANCELLED`. `Dispute.status` is one of `OPEN`, `RESOLVED_UPHELD`, `RESOLVED_REJECTED`, or `WITHDRAWN`, and its `reason_code` is one of `NO_SHOW`, `INCOMPLETE_SERVICE`, `WRONG_DURATION`, or `OTHER`. `LedgerEntry.entry_kind` is one of `EARNED`, `SPENT`, `REDEMPTION`, `ADMIN_ADJUSTMENT`, or `DISPUTE_REVERSAL`.

### 2.5. The Logical Clock and Time Semantics

Every deadline, expiry, and time-gated transition in the system is evaluated against a single server-side logical clock; the host's wall clock is never consulted for business rules. At boot the logical clock is initialized to `2026-03-01T00:00:00Z`. A `PlatformAdmin` may advance the clock explicitly by supplying a new instant as the `to_iso8601` input to the clock-advance capability. Each advance lazily fires every time-gated auto-transition whose preconditions the new clock value has just satisfied, in the following order: a `SkillRequest` whose `latest_start_utc` has been passed while its `status` is still `OPEN` transitions to `EXPIRED`; a `ShiftAssignment` still `CONFIRMED` past the shift's end without a check-in transitions to `NO_SHOW`; a `ShiftAssignment` in `CHECKED_IN` past the shift's end transitions to `COMPLETED`; a `ProjectShift` whose end has passed and all of whose assignments are in `COMPLETED`, `NO_SHOW`, or `CANCELLED` — with at least one in `COMPLETED` — transitions from `FILLED` to `COMPLETED`; a `GroupProject` in `OPEN` whose earliest shift start has arrived advances to `IN_PROGRESS`; and a `GroupProject` in `IN_PROGRESS` whose window has ended advances to `COMPLETED` or `CANCELLED` per §2.9's aggregate-state resolver. After the sweep, `Member.no_show_strikes` is recomputed for any member whose new `NO_SHOW` roll changed the count.

### 2.6. Ledger Integrity and Balance Reconciliation

The ledger is a strict append-only log: once a `LedgerEntry` is posted, its `delta_minutes`, `posted_at`, `entry_kind`, `memo`, `member_id`, `exchange_id`, and `redemption_id` are immutable. Corrections take the form of a compensating entry, never a rewrite. `EARNED` and positive `ADMIN_ADJUSTMENT` entries carry positive `delta_minutes`; `SPENT`, `REDEMPTION`, and `DISPUTE_REVERSAL` entries carry negative `delta_minutes`. The `memo` field is optional on every kind except `ADMIN_ADJUSTMENT`, where it is required. An entry's `exchange_id` is populated when the entry originates from an exchange settlement (`EARNED`, `SPENT`, or `DISPUTE_REVERSAL` posted on a dispute-upheld settlement) and is null on `REDEMPTION` and `ADMIN_ADJUSTMENT` entries; its `redemption_id` is populated only on `REDEMPTION` entries and is null on all other kinds.

Every member carries two ledger-derived balance views on their record, both integer minutes and both exact. The **chronological balance**, exposed as `chronological_balance_minutes`, is the ordered replay of every `LedgerEntry` belonging to the member: the entries are sorted with `posted_at` ascending as the primary key and `LedgerEntry.created_at` ascending as the secondary key — the entry `id` is never used as a tiebreak — and the running total starts at zero and adds each entry's `delta_minutes` in that order. No status filter is applied, since the ledger has no in-flight state. This balance is recomputed on every insert into the ledger for the member.

The **forward-looking balance**, exposed as `forward_looking_balance_minutes`, is the chronological balance minus the sum of `Exchange.committed_minutes` across every exchange where `requester_member_id` equals the member and `status` is either `SCHEDULED` or `DELIVERED` — that is, minus the total pending debit the member has already committed but not yet spent. It is recomputed on every ledger insert for the member and on every exchange creation or cancellation involving the member. Two variants of this same underlying calculation surface in different contexts: the **chronological variant** — the plain chronological balance with no pending subtraction — is what impact reporting, historical audits, and dispute reconstruction consume, because it treats the ledger as final at each `posted_at`; the **forward-looking variant** — the chronological balance minus pending `SCHEDULED` and `DELIVERED` obligations — is what gates redemption authorisation and the exchange-creation ceiling, so that a member cannot double-commit hours they have already promised to another exchange.

Beyond the two balances, each member's record carries `lifetime_earned_minutes` — the sum of positive `delta_minutes` on ledger entries with `entry_kind` equal to `EARNED` — and `lifetime_redeemed_minutes` — the sum of the absolute values of `delta_minutes` on ledger entries with `entry_kind` equal to `REDEMPTION`.

### 2.7. Trust, Verification, and the Peer Model

`Member.trust_tier` is a computed enumeration derived from two counters: `verified_credential_count`, the count of `VerificationCredential` rows whose subject is the member and whose `status` is `VERIFIED`; and `completed_exchange_count`, the count of `Exchange` rows where the member is the `provider_member_id` and the `status` is `SETTLED`. The tier is resolved by evaluating four branches in the following pinned order, and the first branch whose predicates match is selected: if `verified_credential_count` is at least 3 **and** `completed_exchange_count` is at least 20, the tier is `ANCHOR`; otherwise, if `verified_credential_count` is at least 2 **and** `completed_exchange_count` is at least 5, the tier is `TRUSTED`; otherwise, if `verified_credential_count` is at least 1, the tier is `BASIC`; otherwise, the tier is `UNVERIFIED`. Comparisons are integer `>=` and no identifier fallback is consulted. The tier is recomputed whenever a `VerificationCredential` is verified and whenever a provider's `completed_exchange_count` changes on exchange settlement.

Trust tiers order strictly `UNVERIFIED < BASIC < TRUSTED < ANCHOR`. Verification is a peer act, not a self-attestation: only a `Member` whose own `trust_tier` is `TRUSTED` or `ANCHOR` may verify, reject, or request a revision on another member's credential, and a member may never verify a credential whose subject is themselves. A verifier who fails either gate is rejected with `ERR_VERIFIER_INELIGIBLE`.

### 2.8. Optimistic Concurrency Control on Member Version

`Member.version` is incremented on every mutation that materially alters the member's balance surface — most notably, exchange settlement, ledger admin adjustment, redemption creation, redemption fulfilment, and a verification credential's flip to `VERIFIED`. Because a client reading a member's balance can be racing a background settlement that has already advanced the counter, the create-redemption path is guarded by optimistic concurrency control. A create-redemption request must carry `expected_member_version` as a non-optional integer field equal to the `Member.version` the client last observed. If that value does not equal the member's current `Member.version` at the moment the create is processed, the request is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412) — the balance the client is spending against is no longer authoritative, and the client must re-read the member and retry with the current version. This is a stale-version rejection, not a race between simultaneous writers: the check compares the client's captured version to the server's current version, without regard to how many other writers arrived in between. Endpoints not covered by this rule do not accept a version field.

### 2.9. Compound State and Cascading Side Effects

`GroupProject.aggregate_state` is not written directly; it is computed from the project's own status, its window, and the statuses of its `ProjectShift` rows, and it is recomputed on every project or shift status write and on every clock advance. The resolver evaluates the following branches top-to-bottom and returns the first match: if the project has been cancelled, the state is `CANCELLED`; if the project has not yet been published, the state is `PLANNING`; if the logical clock has advanced past `window_end_utc`, the resolver computes the completion ratio — the number of shifts with `status` equal to `COMPLETED` divided by the total number of shifts (or 0 if there are none) — and compares it against `minimum_completed_ratio` rounded half-up to two decimal places; if the ratio is at least the minimum, the state is `COMPLETED`, otherwise it is `CANCELLED`; if the logical clock has reached the earliest `shift_start_utc` across the project's shifts, the state is `IN_PROGRESS`; otherwise, the state is `OPEN`. The `minimum_completed_ratio` is a decimal in the open-lower, closed-upper interval from 0 to 1 with two decimal places, defaulting to 0.60.

`ProjectShift.status` is likewise derived from the counts of its `ShiftAssignment` rows and the clock. `GroupProject.total_committed_minutes` — the sum of `duration_minutes` across the project's shifts whose `status` is `FILLED` — is recomputed on every assignment write, so it bubbles up from the assignment layer to the shift layer to the project layer without any explicit publication step. When a `GroupProject` is cancelled from `PLANNING` or `OPEN`, the cancel cascades: every `ProjectShift` whose `status` is `OPEN` or `FILLED` transitions to `CANCELLED`, and every `ShiftAssignment` under a cancelled shift whose `status` is `CONFIRMED` transitions to `CANCELLED`. On any mutation, `updated_at` and `version` on the mutated resource advance, and derived-field recomputation happens synchronously — a client reading a project after a shift status write will already observe the propagated `total_committed_minutes` and `aggregate_state`.

### 2.10. Precision and Rounding

Every quantity that participates in the ledger — `delta_minutes`, `committed_minutes`, `claimed_delta_minutes`, `duration_minutes`, `minutes_per_session`, `needed_minutes`, `minutes_cost`, `no_show_strikes`, `chronological_balance_minutes`, `forward_looking_balance_minutes`, `lifetime_earned_minutes`, `lifetime_redeemed_minutes`, `verified_credential_count`, `completed_exchange_count`, and `total_committed_minutes` — is an integer and is stored, compared, and returned exactly. Session-length and duration inputs are additionally required to be multiples of 15 in the closed interval from 15 to 480; the admin adjustment amount is a nonzero signed integer multiple of 15 in the closed interval from -4800 to 4800 (a submitted `delta_minutes` of 0 is rejected with `ERR_INVALID_REQUEST`).

Decimal quantities appear in two places. `GroupProject.minimum_completed_ratio` is a decimal with two fractional digits, and the completion-ratio comparison against it uses round-half-up at two decimal places before the `>=` test. `ImpactReport.total_hours_exchanged` is a decimal with two fractional digits and is computed with round-half-up: for each settled exchange within the reporting month, the exchange's `committed_minutes` is divided by 60 and the result is rounded half-up to two decimal places; those per-exchange rounded values are then summed; and the final sum is rounded half-up to two decimal places. This per-exchange-then-sum order is fixed — rounding once at the end would produce a different value in some months, and impact reports must reproduce a single canonical total.

### 2.11. Suspension, Safety Gates, and Validation Priority

`Member.no_show_strikes` is a rolling 90-day count of `NO_SHOW` `ShiftAssignment` rows for the member — an assignment counts toward the tally if the sum of its shift's `shift_start_utc` and `duration_minutes` is at or after the cutoff obtained by subtracting 90 days from the logical clock. It is recomputed on every assignment status write and lazily on member read when any assignment's shift-end has aged out. The moment the count reaches 3, `Member.is_suspended` is set to true as a cascading side effect of the third `NO_SHOW`; the transition to true is not a separate write step but happens in the same operation that produced the third strike. Once set to true, `is_suspended` is sticky — it is never reset to false by the strike recomputation, even after strikes age out of the 90-day window and `no_show_strikes` drops back below 3. A suspended member is barred from creating a new exchange, self-assigning to a shift, or creating a redemption — each such request is rejected with `ERR_MEMBER_SUSPENDED`.

Validation is layered and priority-ordered. When multiple checks would fire on the same request, they are evaluated in the following order and the first failure wins, so that authentication failures are never masked by later domain checks and role failures are never masked by resource-existence failures. Header presence and syntactic validity are checked first, then the role allow-list, then left-to-right existence of every path-referenced resource (a missing resource is rejected with `ERR_RESOURCE_NOT_FOUND`), then whether the target resource is in a state that permits the operation (per §3), then the redemption OCC gate (§2.8), then owner-match and requester-provider distinctness, then the suspension gate, then the fiscal balance gate — where the requester's `forward_looking_balance_minutes` must be at least the exchange's `committed_minutes` on exchange creation and at least the redemption's `minutes_cost` on redemption creation. Below the fiscal gate come the temporal overlap gates: for a shift assignment, the requested assignment's interval — closed on the left at `shift_start_utc`, open on the right at `shift_start_utc + duration_minutes` — must not overlap another `CONFIRMED` or `CHECKED_IN` assignment held by the same member, with intervals touching at the endpoints allowed; a violation is rejected with `ERR_SHIFT_TIME_CONFLICT`. For an exchange, the requested exchange's interval — closed on the left at `scheduled_start_utc`, open on the right at `scheduled_start_utc + committed_minutes` — is extended by a 30-minute travel buffer on both sides, and the resulting extended window must not overlap another `SCHEDULED` or `DELIVERED` exchange in which the same member participates; a violation is rejected with `ERR_EXCHANGE_TIME_CONFLICT`. Only after all of these do the business-referential and business-constraint gates run: an exchange creation additionally requires that the referenced `SkillRequest.status` is `OPEN` and the referenced `SkillOffer.status` is `ACTIVE` (rejected with `ERR_INVALID_STATE` when either is not), and requires the requester's `trust_tier` to be at least the offer's `required_trust_tier` in the tier ordering `UNVERIFIED < BASIC < TRUSTED < ANCHOR` (rejected with `ERR_TRUST_TIER_TOO_LOW` otherwise). A verifier-eligibility check applies to peer verification actions on credentials — the acting member's `trust_tier` must be in `TRUSTED` or `ANCHOR` and cannot equal `subject_member_id` on the credential (`ERR_VERIFIER_INELIGIBLE`). Schema-shape validation — required fields present, enum values in the allowed set, minute inputs as integer multiples of 15 in the closed interval from 15 to 480, `latest_start_utc` strictly greater than `earliest_start_utc`, `window_end_utc` strictly greater than `window_start_utc`, ISO 8601 UTC datetimes — runs as the last band of checks and produces `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Member Onboarding, the Trust Ladder, and Peer Verification

A new member joins the platform anonymously by supplying an `email`, a `display_name`, and a `home_neighborhood` code such as `NW-01`. The server creates the `Member` row with `trust_tier` at `UNVERIFIED`; `chronological_balance_minutes`, `forward_looking_balance_minutes`, `lifetime_earned_minutes`, `lifetime_redeemed_minutes`, `verified_credential_count`, `completed_exchange_count`, and `no_show_strikes` all at zero; `is_suspended` at false; and `version` at 1. The `email` must be unique across active members.

The trust ladder climbs on peer attestation, not self-declaration. A subject who wants to move up submits a `VerificationCredential` naming themselves as `subject_member_id` (the acting `X-User-ID` must equal `subject_member_id`), nominating a `verifier_member_id`, and supplying a `credential_type` — `ID_CHECK`, `SKILL_ATTEST`, or `REFERENCE_ATTEST` — together with an `evidence_url` pointing to the supporting document. When the type is `SKILL_ATTEST`, a `skill_code` must accompany the submission; for the other two types, `skill_code` is absent. Both `subject_member_id` and `verifier_member_id` must reference existing members, but the subject-not-verifier constraint and the verifier's trust-tier gate are not enforced at submission time — they are checked only when the verifier attempts to act on the credential (§3.1 below and §2.7). The credential starts in `SUBMITTED` with `revision_round` at zero.

From `SUBMITTED`, the nominated verifier — who must be a different member from the subject and must currently hold `TRUSTED` or `ANCHOR` — may advance the credential to `VERIFIED`, transition it to `REJECTED`, or ask the subject for a revision, which moves the credential from `SUBMITTED` to `REVISION_REQUESTED` provided the credential's `revision_round` is still less than 2. A revision loop is bounded at two rounds: the subject resubmits by supplying a fresh `evidence_url`, which returns the credential from `REVISION_REQUESTED` to `SUBMITTED` and increments `revision_round` by one, but only while `revision_round` is less than 2. Once two revisions have been consumed, the credential cannot re-enter `SUBMITTED` — it must be either verified or rejected. A verifier may reject a credential from `REVISION_REQUESTED` as well as from `SUBMITTED`; the reject from `REVISION_REQUESTED` does not require the trust-tier gate (the tier gate only applies to the transitions out of `SUBMITTED`), but it does require that the acting member is the credential's `verifier_member_id`. `REVISION_REQUESTED` cannot flip directly to `VERIFIED`: verification is always a transition out of `SUBMITTED`, so the subject must resubmit first.

When a credential transitions to `VERIFIED`, three effects fire in the same operation: the credential's `status` becomes `VERIFIED`, the subject's `verified_credential_count` is incremented by 1, and the subject's `trust_tier` is recomputed against the pinned ladder in §2.7; if the recompute upgrades the tier, the tier field simply changes value on the next read of the member. This recompute — plus the accompanying `Member.version` bump on the subject — is what the create-redemption OCC gate observes: a client whose balance was read before a credential was verified will find its captured `Member.version` stale. The verifier gate — trust tier at `TRUSTED` or `ANCHOR` and the subject-not-verifier rule — is enforced on every attempt to verify, reject, or request revision; a caller who fails either gate receives `ERR_VERIFIER_INELIGIBLE` (HTTP 403), and a caller who is not the credential's `verifier_member_id` receives `ERR_OWNERSHIP_VIOLATION` in the same priority band.

### 3.2. Skill Offers, Skill Requests, and the Matching Surface

A member advertises their willingness to help by creating a `SkillOffer`. The offer's `member_id` must equal the acting member, its `skill_code` — for example, `GARDENING` or `TUTORING_MATH` — must be drawn from the platform's declared skill taxonomy, and its `title` is a short public label. Every offer commits to a fixed session length, `minutes_per_session`, which must be an integer multiple of 15 in the closed interval from 15 to 480 minutes; an offer may also declare a `required_trust_tier` (defaulting to `UNVERIFIED`) that a requester must meet or exceed before booking. Offers begin in `ACTIVE`.

An offer's owner may pause an active offer, taking it to `PAUSED`, resume a paused offer back to `ACTIVE`, or archive an active offer to the terminal `ARCHIVED` state. `PAUSED` and `ARCHIVED` offers are invisible to the matching surface — a requester cannot book an offer whose `status` is not `ACTIVE`, and an attempt to do so is rejected with `ERR_INVALID_STATE` in the exchange-creation priority band.

A member who needs help posts a `SkillRequest` naming the desired `skill_code`, the `needed_minutes` (a multiple of 15 in the closed interval from 15 to 480), an `earliest_start_utc`, and a `latest_start_utc` strictly greater than the earliest. The request begins in `OPEN`. From `OPEN` it may reach `MATCHED` when an exchange references it, `EXPIRED` when the logical clock advances past `latest_start_utc` while the request is still `OPEN`, or `CANCELLED` when its owner withdraws it. From `MATCHED` it either returns to `OPEN` if the linked exchange is cancelled or advances to `CLOSED` when the linked exchange settles.

### 3.3. Booking, Delivering, and Settling an Exchange

The exchange is the atomic unit of one-to-one help. A requester books by referencing an `offer_id` and a `request_id`, agreeing on a `scheduled_start_utc`, and committing to a number of `committed_minutes`. Only the requester may drive creation — the acting member (as resolved by `X-User-ID`) must equal the request's `member_id`, and a create attempt driven by the provider or any third party is rejected with `ERR_OWNERSHIP_VIOLATION`. On creation the server copies `provider_member_id` from the offer's `member_id` and `requester_member_id` from the request's `member_id`. `committed_minutes` must equal the offer's `minutes_per_session`, and the `scheduled_start_utc` must lie within the closed interval bounded by the request's `earliest_start_utc` and `latest_start_utc`.

Multiple gates apply on creation, and their ordering matters. The requester and provider must resolve to different members (`ERR_OWNERSHIP_VIOLATION`). The acting member must not be suspended (`ERR_MEMBER_SUSPENDED`). The requester's `forward_looking_balance_minutes` must be at least `committed_minutes`, so that the pending debit implied by the booking cannot overdraw the account beyond commitments already in flight; a shortfall is rejected with `ERR_INSUFFICIENT_BALANCE`. The exchange's interval, closed on the left at `scheduled_start_utc` and open on the right at `scheduled_start_utc + committed_minutes`, is extended by a 30-minute travel buffer on both sides; if the extended window overlaps another `SCHEDULED` or `DELIVERED` exchange in which the same member participates on either side, the request fails with `ERR_EXCHANGE_TIME_CONFLICT`. The referenced request must be `OPEN` and the referenced offer must be `ACTIVE`, and the requester's `trust_tier` must be at least the offer's `required_trust_tier` in the ordering `UNVERIFIED < BASIC < TRUSTED < ANCHOR`, or the request is rejected with `ERR_TRUST_TIER_TOO_LOW`. When all gates pass, the exchange is inserted with `status` at `SCHEDULED`, the linked request transitions from `OPEN` to `MATCHED`, and the requester's `forward_looking_balance_minutes` is recomputed to reflect the new pending debit.

After the scheduled start has arrived on the logical clock — that is, once the clock has reached or passed `scheduled_start_utc` — the provider marks the exchange delivered, transitioning `SCHEDULED → DELIVERED`. Only the provider may drive this transition, only from `SCHEDULED`, and only when the clock has reached the scheduled start; other callers or an early call are rejected with `ERR_OWNERSHIP_VIOLATION` or `ERR_INVALID_STATE` respectively.

The requester settles the exchange, transitioning `DELIVERED → SETTLED`. Settlement is gated on three preconditions: the acting member must be the exchange's `requester_member_id`, the logical clock must have reached or passed the end of the session (`scheduled_start_utc` plus `committed_minutes` minutes), and no dispute referencing the exchange may currently be `OPEN`. When these hold, five effects fire in one operation: the exchange's `status` becomes `SETTLED` and `settled_at_utc` is written from the logical clock; a `SPENT` `LedgerEntry` is inserted for the requester with `delta_minutes` equal to the negative of `committed_minutes`; an `EARNED` `LedgerEntry` is inserted for the provider with `delta_minutes` equal to the positive of `committed_minutes`; both members' `chronological_balance_minutes` and `forward_looking_balance_minutes` are recomputed; the provider's `completed_exchange_count` is recomputed, which in turn may promote their `trust_tier` under the pinned ladder in §2.7; and the linked request's `status` transitions `MATCHED → CLOSED`.

Before the scheduled start arrives, either the provider or the requester may cancel a `SCHEDULED` exchange, transitioning `SCHEDULED → CANCELLED`. The cancel is only accepted while the clock is strictly earlier than `scheduled_start_utc`; a cancel arriving on or after the start is rejected with `ERR_INVALID_STATE`. The cancel writes the exchange to `CANCELLED` and rolls the linked request back from `MATCHED` to `OPEN`, so a fresh exchange can be booked against it.

### 3.4. Disputes and Reduced-Credit Settlement

A dispute is filed against a `DELIVERED` exchange when either party feels the session was not honoured. The filer supplies `exchange_id`, `raised_by_member_id` (which must equal either the exchange's requester or provider), a `reason_code` — `NO_SHOW`, `INCOMPLETE_SERVICE`, `WRONG_DURATION`, or `OTHER` — and `claimed_delta_minutes`, the number of minutes the raiser argues should be adjusted; the last must be a positive integer multiple of 15 in the closed interval from 15 to 480, and the acting member (`X-User-ID`) must equal `raised_by_member_id`. On file, the dispute is inserted with `status` at `OPEN`, and as a system side effect the underlying exchange transitions `DELIVERED → DISPUTED`. While the dispute is `OPEN`, the requester cannot drive settlement — the no-open-dispute precondition on the settle transition fails with `ERR_INVALID_STATE`.

A dispute leaves `OPEN` along one of three paths. The raiser may withdraw the dispute, taking it to `WITHDRAWN`; withdrawal returns the exchange from `DISPUTED` back to `DELIVERED` so the requester can drive normal settlement. A `PlatformAdmin` resolves the dispute by supplying an `outcome`, either `UPHELD` or `REJECTED`, together with `admin_notes`. When the outcome is `REJECTED`, the dispute reaches `RESOLVED_REJECTED` and the exchange returns from `DISPUTED` to `DELIVERED`, resuming the normal settlement path with no ledger effect; `admin_notes` may be blank in this case. When the outcome is `UPHELD`, the dispute reaches `RESOLVED_UPHELD` — `admin_notes` is required on this branch and rejected with `ERR_INVALID_REQUEST` if omitted — and the exchange is driven directly through settlement with reduced credit: the exchange's `status` becomes `SETTLED`, `settled_at_utc` is written from the logical clock, and three ledger entries are posted in the same operation. For the requester, a `SPENT` entry with `delta_minutes` equal to the negative of the exchange's `committed_minutes` less the dispute's `claimed_delta_minutes`. For the provider, an `EARNED` entry with `delta_minutes` equal to the positive of that same reduced amount. And for the party opposite `raised_by_member_id` — the deficient party — a `DISPUTE_REVERSAL` entry with `delta_minutes` equal to the negative of `claimed_delta_minutes`, its `memo` set to the dispute's `id`. Both members' balances are then recomputed, the provider's `completed_exchange_count` and `trust_tier` are refreshed, and, as the same cascade that a normal settle performs, the linked `SkillRequest` transitions `MATCHED → CLOSED`.

### 3.5. Group Projects, Shifts, and Assignments

A `ProjectOrganizer` scaffolds a multi-member effort by creating a `GroupProject` with an `organizer_member_id`, a `title`, a `window_start_utc`, a `window_end_utc` strictly greater than the start, and optionally a `minimum_completed_ratio` (defaulting to 0.60). The project begins in `aggregate_state` `PLANNING`. In `PLANNING` — and, once the project has been published, also while it is `OPEN` — the organizer builds out the roster of `ProjectShift` entries under the project, each carrying a `project_id` binding it to its parent, a `role_label` such as `PACKER` or `DRIVER`, a `shift_start_utc` lying within the closed interval bounded by the project's `window_start_utc` and `window_end_utc`, a `duration_minutes` (a multiple of 15 in the closed interval from 15 to 480), and a positive `capacity` — the maximum number of concurrent assignments. A shift-create attempt against a project whose `aggregate_state` is anything other than `PLANNING` or `OPEN` is rejected with `ERR_INVALID_STATE`. Every shift begins in `OPEN`.

Publishing takes the project from `PLANNING` to `OPEN`, and the transition is gated on three preconditions: the acting member is the project's organizer, at least one shift already exists under the project, and the logical clock has not yet reached `window_start_utc` (the check is a strict `>`, so a publish exactly at `window_start_utc` is still accepted). Once published, members self-assign to open shifts; the parent project's `aggregate_state` must be `OPEN` or `IN_PROGRESS` at the moment of the assignment (an assignment against a `PLANNING`, `COMPLETED`, or `CANCELLED` project is rejected with `ERR_INVALID_STATE`). A member's self-assignment creates a `ShiftAssignment` naming the `shift_id` and their own `member_id`; the assignment starts in `CONFIRMED`. Assignments are gated on the suspension check and on the shift-overlap check in §2.11 — a `CONFIRMED` or `CHECKED_IN` assignment on any other shift whose interval overlaps the target shift's interval blocks the create with `ERR_SHIFT_TIME_CONFLICT`, though endpoint-touching adjacency is allowed. When the count of `CONFIRMED` assignments on a shift equals the shift's `capacity`, the shift transitions from `OPEN` to `FILLED`, the project's `total_committed_minutes` bubbles up to include the shift's `duration_minutes`, and the derived state cascades. When an assignment is cancelled and the confirmed-count drops back below capacity, a `FILLED` shift returns to `OPEN` and `total_committed_minutes` is recomputed downward.

A member may cancel their own `CONFIRMED` assignment while the logical clock is strictly earlier than the shift's `shift_start_utc`; the assignment transitions to `CANCELLED`. After the shift start has been reached but before its end, the member may check in, transitioning `CONFIRMED → CHECKED_IN` and writing `check_in_utc` from the logical clock. If the clock advances past the shift's end (that is, past `shift_start_utc + duration_minutes` minutes) without a check-in, the assignment is rolled forward to `NO_SHOW` — this triggers a recompute of the member's `no_show_strikes`, and if the recompute yields a count of at least 3, `is_suspended` is set to true in the same operation as a cascading side effect. If the clock advances past the shift's end after the member has checked in, the assignment rolls to `COMPLETED`.

Once the clock has passed a `FILLED` shift's end and every assignment on the shift is in `COMPLETED`, `NO_SHOW`, or `CANCELLED` — with at least one in `COMPLETED` — the shift transitions from `FILLED` to `COMPLETED`, and in the same operation an `EARNED` `LedgerEntry` is inserted for each completed member with `delta_minutes` equal to the positive of the shift's `duration_minutes`; each affected member's balances are then recomputed. `GroupProject.aggregate_state` is re-derived from the resolver in §2.9 on every shift or assignment status write, and on every clock advance, so the project's state and `total_committed_minutes` are always consistent with the current shift roster.

An organizer may cancel the project. From `PLANNING`, the cancel is unconditional beyond ownership: the project's aggregate state becomes `CANCELLED`, every `OPEN` or `FILLED` shift is cascaded to `CANCELLED`, and every `CONFIRMED` assignment under those shifts is cascaded to `CANCELLED`. From `OPEN`, the cancel is accepted only while the logical clock is still strictly earlier than the earliest `shift_start_utc` across the project's shifts; the same cascade applies to shifts, and assignments follow their shift's cascade. Once any shift has started, the project cannot be cancelled — it must run to its window end, where the aggregate-state resolver decides between `COMPLETED` and `CANCELLED` based on the completion ratio.

### 3.6. Redemptions and the Reward Flow

Members spend accumulated hours by requesting a reward from the platform catalogue. The request supplies the member's own `member_id`, a `reward_code` such as `FARMERS_MARKET_15` or `BUS_PASS_60`, and `expected_member_version` — the `Member.version` the client observed on its most recent read of the member. The server sets `minutes_cost` from the reward catalogue as a positive integer; the client does not supply it. The catalogue includes a fixed roster of named codes and, for any additional code that ends with an underscore followed by a positive integer (as with the examples above), the trailing integer is taken as the `minutes_cost`; a `reward_code` that neither appears in the fixed roster nor matches the trailing-integer form is rejected with `ERR_INVALID_REQUEST`. The redemption is inserted with `status` at `REQUESTED` and `fulfilled_at_utc` at null, and `Member.version` is incremented by 1 because a redemption is a member-scoped mutation.

Two gates fire on create. The forward-looking-balance gate requires that the member's `forward_looking_balance_minutes` is at least the reward's `minutes_cost` — a shortfall is rejected with `ERR_INSUFFICIENT_BALANCE`. And the version gate rejects the create with `ERR_STALE_MEMBER_VERSION` (HTTP 412) when the client's `expected_member_version` does not equal the current `Member.version`; the client is spending against a balance that a background settlement, credential verification, admin ledger adjustment, or earlier redemption has already advanced past.

A `PlatformAdmin` fulfils the redemption, transitioning `REQUESTED → FULFILLED`. Fulfilment re-checks the balance gate against the member's current `forward_looking_balance_minutes` — since time may have passed since the create and new pending debits may have accumulated — and if the balance still covers the cost, the redemption's `status` becomes `FULFILLED`, `fulfilled_at_utc` is written from the logical clock, a `REDEMPTION` `LedgerEntry` is posted with `delta_minutes` equal to the negative of `minutes_cost`, the member's `chronological_balance_minutes`, `forward_looking_balance_minutes`, and `lifetime_redeemed_minutes` are recomputed, and `Member.version` is bumped by 1. Alternatively, a `PlatformAdmin` may void a `REQUESTED` redemption; voiding transitions `REQUESTED → VOIDED` without posting a ledger entry and without spending hours. `FULFILLED` and `VOIDED` are terminal.

### 3.7. Impact Reporting and Administrative Ledger Adjustment

At month's end, a `PlatformAdmin` generates an `ImpactReport` for a specific `report_month` in `YYYY-MM` form. The report captures three summary metrics for the calendar month, evaluated inclusive of the first instant of the month and exclusive of the first instant of the following month. `total_hours_exchanged` is the round-half-up sum of hours across settled exchanges: for every exchange whose `status` is `SETTLED` and whose `settled_at_utc` falls within the reporting month, the exchange's `committed_minutes` divided by 60 is rounded half-up to two decimal places; those per-exchange rounded values are summed; and the final total is rounded half-up to two decimal places. This gross figure includes exchanges that reached `SETTLED` via a dispute-upheld reduced credit, and it uses the full `committed_minutes` value rather than the reduced credit — the corresponding net-hours audit view, which sums only `EARNED` `LedgerEntry` rows with `posted_at` in the month and therefore reflects the reduced credit for dispute-upheld exchanges, is used only for internal ledger reconciliation. `unique_active_members` is the count of distinct `member_id` values on ledger entries whose `posted_at` falls in the month. And `top_skill_code` is the `skill_code` appearing on the most `SETTLED` exchanges in the month, where each exchange's contributing `skill_code` is read from the exchange's linked `SkillOffer.skill_code`; if no exchange in the month is `SETTLED`, `top_skill_code` is `null`. The tie-break sequence is pinned: among tied skill codes, the code whose earliest settled exchange in the month has the earliest `settled_at_utc` wins; if still tied, the earlier `LedgerEntry.posted_at` — restricted to entries whose `entry_kind` is `EARNED`, `SPENT`, or `DISPUTE_REVERSAL` (the only kinds with a non-null `exchange_id`) and whose linked offer's `skill_code` is one of the still-tied codes — wins; and if still tied, the alphabetically smaller `skill_code` (ASCII) wins. No identifier fallback is ever consulted. The report also records `generated_by_user_id`, the opaque `X-User-ID` of the admin who generated it.

A `PlatformAdmin` may also seed or correct balances directly through the admin-adjustment capability. The admin supplies a `member_id`, a `delta_minutes` value that is a signed integer multiple of 15 in the closed interval from -4800 to 4800, and a `memo` — required for this entry kind. The server inserts a `LedgerEntry` with `entry_kind` `ADMIN_ADJUSTMENT` and `posted_at` equal to the logical clock, recomputes the member's `chronological_balance_minutes` and `forward_looking_balance_minutes`, and increments `Member.version` by 1 so that any in-flight client observations are correctly invalidated at the next redemption check.

## 4. Endpoint Definitions

All endpoints return the standard envelope defined in §2.2. Creation operations that insert a new resource return HTTP 201; all other successful mutations and reads return HTTP 200. Error responses use the codes documented in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the server's logical clock and fire time-gated auto-transitions. | PlatformAdmin |
| POST | /_ledger/admin-adjust | Post an ADMIN_ADJUSTMENT ledger entry to seed or correct a member's balance. | PlatformAdmin |
| POST | /members | Register a new member. | Anonymous |
| GET | /members | List members with optional filters. | Member, ProjectOrganizer, PlatformAdmin |
| GET | /members/{id} | Fetch a member's public and balance fields. | Member, ProjectOrganizer, PlatformAdmin |
| GET | /members/{id}/ledger-entries | List a member's ledger entries chronologically. | Member, PlatformAdmin |
| POST | /skill-offers | Create a skill offer owned by the acting member. | Member |
| GET | /skill-offers | List skill offers with filters. | Member, ProjectOrganizer, PlatformAdmin |
| GET | /skill-offers/{id} | Fetch a skill offer. | Member, ProjectOrganizer, PlatformAdmin |
| POST | /skill-offers/{id}/pause | Pause an active offer. | Member |
| POST | /skill-offers/{id}/resume | Resume a paused offer. | Member |
| POST | /skill-offers/{id}/archive | Archive an active offer. | Member |
| POST | /skill-requests | Create a skill request. | Member |
| GET | /skill-requests | List skill requests with filters. | Member, ProjectOrganizer, PlatformAdmin |
| GET | /skill-requests/{id} | Fetch a skill request. | Member, ProjectOrganizer, PlatformAdmin |
| POST | /skill-requests/{id}/cancel | Cancel an open skill request. | Member |
| POST | /exchanges | Create an exchange linking an offer and a request. | Member |
| GET | /exchanges | List exchanges with filters. | Member, PlatformAdmin |
| GET | /exchanges/{id} | Fetch an exchange. | Member, PlatformAdmin |
| POST | /exchanges/{id}/mark-delivered | Provider marks the exchange delivered. | Member |
| POST | /exchanges/{id}/settle | Requester settles the delivered exchange. | Member |
| POST | /exchanges/{id}/cancel | Cancel a scheduled exchange before its start. | Member |
| GET | /ledger-entries | List ledger entries with filters. | Member, PlatformAdmin |
| GET | /ledger-entries/{id} | Fetch a single ledger entry. | Member, PlatformAdmin |
| POST | /redemptions | Redeem hours for a reward (OCC-guarded). | Member |
| GET | /redemptions | List redemptions with filters. | Member, PlatformAdmin |
| GET | /redemptions/{id} | Fetch a redemption. | Member, PlatformAdmin |
| POST | /redemptions/{id}/fulfill | Fulfil a requested redemption; re-checks balance. | PlatformAdmin |
| POST | /redemptions/{id}/void | Void a requested redemption without spending hours. | PlatformAdmin |
| POST | /credentials | Submit a verification credential. | Member |
| GET | /credentials | List verification credentials with filters. | Member, PlatformAdmin |
| GET | /credentials/{id} | Fetch a verification credential. | Member, PlatformAdmin |
| POST | /credentials/{id}/verify | Verifier approves a credential. | Member |
| POST | /credentials/{id}/reject | Verifier rejects a credential. | Member |
| POST | /credentials/{id}/request-revision | Verifier asks the subject for a revision. | Member |
| POST | /credentials/{id}/resubmit | Subject resubmits a credential with new evidence. | Member |
| POST | /group-projects | Create a group project. | ProjectOrganizer |
| GET | /group-projects | List group projects with filters. | Member, ProjectOrganizer, PlatformAdmin |
| GET | /group-projects/{id} | Fetch a group project. | Member, ProjectOrganizer, PlatformAdmin |
| POST | /group-projects/{id}/publish | Publish a project from planning to open. | ProjectOrganizer |
| POST | /group-projects/{id}/cancel | Cancel a project; cascade to shifts and assignments. | ProjectOrganizer |
| POST | /group-projects/{id}/shifts | Create a project shift under a project. | ProjectOrganizer |
| GET | /group-projects/{id}/shifts | List shifts under a project. | Member, ProjectOrganizer, PlatformAdmin |
| GET | /shifts/{id} | Fetch a project shift. | Member, ProjectOrganizer, PlatformAdmin |
| POST | /shifts/{id}/assignments | Self-assign to a shift. | Member |
| GET | /shifts/{id}/assignments | List assignments under a shift. | Member, ProjectOrganizer, PlatformAdmin |
| DELETE | /shifts/{sid}/assignments/{id} | Cancel a shift assignment before the shift starts. | Member |
| POST | /assignments/{id}/check-in | Check in to a confirmed assignment inside its window. | Member |
| GET | /assignments/{id} | Fetch a shift assignment. | Member, ProjectOrganizer, PlatformAdmin |
| GET | /assignments | Flat list of shift assignments with filters. | Member, ProjectOrganizer, PlatformAdmin |
| POST | /disputes | File a dispute against a delivered exchange. | Member |
| GET | /disputes | List disputes with filters. | Member, PlatformAdmin |
| GET | /disputes/{id} | Fetch a dispute. | Member, PlatformAdmin |
| POST | /disputes/{id}/resolve | Admin resolves a dispute (upheld or rejected). | PlatformAdmin |
| POST | /disputes/{id}/withdraw | Raiser withdraws an open dispute. | Member |
| POST | /impact-reports | Generate an impact report for a completed month. | PlatformAdmin |
| GET | /impact-reports | List impact reports with filters. | PlatformAdmin |
| GET | /impact-reports/{id} | Fetch an impact report. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_INVALID_REQUEST | 400 |
| ERR_ROLE_NOT_PERMITTED | 403 |
| ERR_OWNERSHIP_VIOLATION | 403 |
| ERR_MEMBER_SUSPENDED | 403 |
| ERR_TRUST_TIER_TOO_LOW | 403 |
| ERR_VERIFIER_INELIGIBLE | 403 |
| ERR_INSUFFICIENT_BALANCE | 402 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SHIFT_TIME_CONFLICT | 409 |
| ERR_EXCHANGE_TIME_CONFLICT | 409 |
| ERR_STALE_MEMBER_VERSION | 412 |
