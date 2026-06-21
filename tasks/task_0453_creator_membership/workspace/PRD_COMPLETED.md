# Creator Membership API — Product Requirements Document

## 1. Introduction

The Creator Membership platform lets independent creators monetize their work through recurring patron memberships, in the spirit of Patreon-style subscription services. A creator publishes a ladder of membership tiers, each carrying its own price and bundle of benefits; patrons pledge to a tier, gain access to exclusive posts and a private messaging channel with the creator, and are billed on a predictable rhythm. The platform sits between the two parties: it runs the billing machinery, collects a commission, sweeps the creator's accumulated earnings into payouts, and operates the win-back programs that try to recover patrons who have lapsed.

What makes this domain demanding is that money and membership state evolve along several axes at once. A pledge has a *membership* life of its own — it can be paused, resumed, upgraded, cancelled, and even reactivated long after it ended — while in parallel its *billing health* drifts from good standing into past-due, grace, and finally lapsed if charges keep failing. Two creators may bill identically priced tiers very differently depending on whether they charge up front or at the end of the month, and whether they bill per month or per published creation. Proration, processing fees, platform commission, wallet credits, and win-back discounts all compound, and every cent must reconcile across charges, pledges, creators, and payouts. This document specifies the full contract: the resources, their state machines, the calculation rules, the validation order, and the exact error vocabulary the API speaks.

A logical clock governs all time-dependent behavior so that billing cycles, grace deadlines, and win-back windows are deterministic and testable rather than tied to wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Resource write paths are flat and peer-level — pledges, charges, posts, conversations, payouts and the rest are addressed as top-level collections keyed by their foreign keys, not nested beneath their owning creator.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_AUTH_CONTEXT`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The platform recognizes exactly three roles, spelled `Creator`, `Patron`, and `PlatformAdmin`.

When `X-User-Role` is `Creator`, `X-User-ID` is the `id` of the acting `Creator`; ownership checks on any resource that references a `Creator` compare the resource's `creator_id` foreign key to `X-User-ID`. A `Creator` owns its tiers, its posts, refunds on its own charges, the creator side of conversations, and its payouts.

When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron`; ownership checks on any resource that references a `Patron` compare the resource's `patron_id` foreign key to `X-User-ID`. A `Patron` owns its pledges, its post-access requests, and the patron side of conversations.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`. The `PlatformAdmin` is the operational role that creates ad-hoc charges, settles charges, sweeps and adjusts payouts, advances the logical clock, and runs the billing cycle. Several automatic, billing-axis transitions are conceptually performed by a `system` actor; in practice these are driven by `PlatformAdmin` settle and run-cycle calls.

When an entity-backed actor (`Creator` or `Patron`) targets a resource it does not own — for example a `Creator` trying to refund a charge belonging to another creator, or a `Patron` pausing someone else's pledge — the request is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check applies to owner-scoped mutations on tiers, posts, pledges, charge refunds, conversations, and messages.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last time the resource changed, and the `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource.

Two record types are immutable audit entries and therefore carry only `id` and `created_at` — they have neither `updated_at` nor `version`. The first is `PostAccess`, an access-grant record minted once when a patron is admitted to a post. The second is `Message`, an append-only entry in a conversation log. For every other resource — `Creator`, `Tier`, `Patron`, `Pledge`, `Charge`, `Post`, `Conversation`, `Payout`, and `WinBackOffer` — all four common fields are present.

Whenever the server adjusts a derived field on a resource (for example, recomputing a creator's `pending_payout_cents`, a tier's `active_pledge_count`, or a pledge's `current_cycle_charged_cents`), that adjustment is itself a mutation: it refreshes the owning resource's `updated_at` and increments its `version`.

### 2.5. Identifier Resolution Order

When a request carries resource identifiers in its path, the server validates them strictly left to right and rejects on the first identifier that names a resource that does not exist. Each missing path identifier maps to its own not-found error: a missing creator yields `ERR_CREATOR_NOT_FOUND`, a tier `ERR_TIER_NOT_FOUND`, a patron `ERR_PATRON_NOT_FOUND`, a pledge `ERR_PLEDGE_NOT_FOUND`, a charge `ERR_CHARGE_NOT_FOUND`, a post `ERR_POST_NOT_FOUND`, a conversation `ERR_CONVERSATION_NOT_FOUND`, a payout `ERR_PAYOUT_NOT_FOUND`, and a win-back offer `ERR_OFFER_NOT_FOUND`. Foreign-key references supplied in a request body — for example a `tier_id`, `creator_id`, `patron_id`, `pledge_id`, `post_id`, or `conversation_id` that names a non-existent target — are likewise rejected with the corresponding not-found error.

### 2.6. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority so that the returned error is deterministic. The order is: first, authentication context (`ERR_MISSING_AUTH_CONTEXT`); second, role authorization (`ERR_UNAUTHORIZED`); third, resource ownership for entity-backed actors on owned resources (`ERR_NOT_RESOURCE_OWNER`); fourth, existence of path-supplied identifiers; fifth, existence of body-supplied foreign keys; sixth, request-body well-formedness — required fields present, enum members valid, and integers within their permitted ranges (`ERR_INVALID_REQUEST`); seventh, the target resource being in a state that permits the requested transition; eighth, cross-entity link integrity (`ERR_CROSS_LINK_MISMATCH`). Domain-specific business rules — membership-interval exclusivity, tier-rank uniqueness, messaging gates, content gates, win-back windows, billing-model matching, payout availability, and optimistic-concurrency checks — are evaluated after these foundational checks, as detailed in their respective subsections below. The general principle: a request must be authenticated, authorized, owned, resolvable, well-formed, and state-legal before any domain rule is judged.

### 2.7. Optimistic Concurrency on Pledge Mutations

Two pledge operations are guarded by optimistic concurrency control so that a client cannot mutate a pledge it has not freshly observed. Both the pause operation and the upgrade operation require the request to carry `expected_pledge_version`, a non-optional field whose value is the `version` of the target `Pledge` that the client last read. If that value does not equal the pledge's current `version` — because some other writer advanced the pledge since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is made.

The rationale differs slightly per operation but the mechanism is identical. An upgrade legitimately supersedes the prior view of the pledge — tier, cycle anchor, and proration baseline all move — so a writer carrying an outdated version is operating on a superseded snapshot. A pause likewise supersedes the prior view because renewal scheduling changes; a stale-version pauser is therefore rejected. The reactivate operation may optionally accept `expected_pledge_version` as well, but it is not required there. No endpoint other than pause and upgrade takes a version field.

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents; there are no fractional cents. Wherever a calculation produces a non-integer cent value — proration, percentage-based processing fees, platform commission, and win-back discounts all can — the result is rounded half up to the nearest whole cent, meaning a residual of exactly one-half cent rounds upward. Each rule below states the precise point at which rounding is applied, because the order of rounding versus summation is significant: a fee rounded per line and then summed can differ from the same fee derived from a summed total, and the per-line order is the canonical one.

### 2.9. Ledger Conservation and Cascading Effects

The platform maintains several derived balances that must stay reconciled as money moves. A patron's `wallet_credit_cents` is a non-negative credit balance applied ahead of the card on the patron's next charge; it starts at zero and is never allowed to go negative. A creator's `pending_payout_cents` tracks the net value of the creator's settled-but-unswept earnings and likewise starts at zero. Each of these balances is adjusted in matched pairs across the charge, refund, and payout lifecycles so that no operation can leave the books drifting: an amount added on one event is removed on its compensating event. The detailed mechanics — which event adds, which removes, and by how much — are described in §3 alongside the workflows that trigger them. A single operation frequently mutates more than one resource (a charge settling touches the charge, its pledge, and the creator; a cancellation touches the pledge, its tier, and possibly a conversation), and every such cascade is part of the operation's contract.

## 3. Business Logic & Workflows

### 3.1. Creators, Tiers, and the Membership Ladder

A `Creator` registers with a public `display_name`, a contact `email`, and an opaque `payout_account_ref` naming the external destination where earnings are sent (creator `email` is not checked for uniqueness; duplicate emails are accepted). Registration also accepts three optional configuration choices that shape every future billing decision for that creator. The `platform_plan` selects the creator's own subscription to the platform and defaults to `STARTER`; it may instead be `PRO` or `PREMIUM`, and it determines the commission rate the platform deducts at payout time. The `billing_mode` is the default billing model the creator offers and defaults to `MONTHLY`, the alternative being `PER_CREATION`. The `charge_timing` decides when new-cycle and proration charges are collected and defaults to `UP_FRONT`, the alternative being `END_OF_MONTH`. On registration the creator's `status` is set to `ACTIVE` and `pending_payout_cents` is initialized to 0.

Each creator builds a ladder of membership tiers. Creating a `Tier` requires the owning `creator_id`, a `name`, the `billing_model` the tier uses (`MONTHLY` or `PER_CREATION`), and a `rank` — a positive integer of at least 1 that orders the tier within the ladder, where a higher rank denotes a more premium tier. The request may also carry `benefit_labels`, a list of benefit-description strings granted to members. Pricing fields depend on the model: a `MONTHLY` tier carries `monthly_fee_cents`, the per-month price, which when present must be at least 100 cents; a `PER_CREATION` tier carries `per_creation_fee_cents`, the charge levied per published paid post, which when present must be at least 50 cents, and `per_creation_monthly_cap_cents`, the ceiling on total per-creation charges within one cycle, which when present must be at least equal to `per_creation_fee_cents`. A new tier is born in `DRAFT` status with `active_pledge_count` initialized to 0.

A tier becomes pledgeable only when its creator publishes it, advancing its `status` from `DRAFT` to `PUBLISHED`. Publish is permitted only when the tier is currently `DRAFT`; publishing a tier in any other state (already `PUBLISHED`, or `RETIRED`) is rejected with `ERR_TIER_NOT_PUBLISHED`. Publishing first verifies that the pricing fields appropriate to the tier's billing model are present — a `MONTHLY` tier must have `monthly_fee_cents`, and a `PER_CREATION` tier must have both `per_creation_fee_cents` and `per_creation_monthly_cap_cents` — failing which the publish is rejected with `ERR_TIER_FIELDS_INCOMPLETE`. Publishing then enforces that no other non-`RETIRED` tier of the same creator already occupies this tier's `rank`; a collision is rejected with `ERR_TIER_RANK_TAKEN`. The `rank` is required to be unique per creator among non-`RETIRED` tiers (enforced at publish time as just described); the `name` is conceptually expected to be unique per creator among non-`RETIRED` tiers, but no name-uniqueness check is enforced — duplicate tier names are accepted.

A creator may eventually retire a tier, moving its `status` from `PUBLISHED` to the terminal `RETIRED`. Retire is permitted only when the tier is currently `PUBLISHED`; retiring a tier in any other state (`DRAFT` or already `RETIRED`) is rejected with `ERR_TIER_NOT_PUBLISHED`. Retirement is permitted only when no pledge on the tier has a `lifecycle_status` of either `ACTIVE` or `PAUSED`; if any such member remains, the retire is rejected with `ERR_TIER_HAS_MEMBERS`. Once retired, the tier is no longer pledgeable, and its `rank` and `name` are freed for reuse by future tiers.

### 3.2. Patrons and the Pledge Lifecycle

A `Patron` registers with a `display_name` and a contact `email` (patron `email` is not checked for uniqueness; duplicate emails are accepted); registration sets the patron's `status` to `ACTIVE` and initializes `wallet_credit_cents` to 0. A patron supports a creator by creating a `Pledge`, supplying the `patron_id`, the `creator_id`, and the `tier_id` of the chosen tier. The pledge may only target a tier whose `status` is `PUBLISHED`; pledging an unpublished tier is rejected with `ERR_TIER_NOT_PUBLISHED`. The chosen tier must belong to the named creator — a mismatch between the pledge's creator and the tier's owner is rejected with `ERR_CROSS_LINK_MISMATCH`.

Membership-interval exclusivity governs how many live pledges a patron may hold against one creator. A patron may have at most one pledge to a given creator whose `lifecycle_status` is `DRAFT`, `ACTIVE`, or `PAUSED` — that is, at most one open membership interval. Attempting to create a second pledge to the same creator while such an interval is occupied is rejected with `ERR_DUPLICATE_PLEDGE`. A `CANCELLED` pledge frees the interval, and reactivation reuses that same pledge row rather than creating a new one.

A newly created pledge begins with `lifecycle_status` of `DRAFT` and `billing_status` of `CURRENT`. Its `billing_model` is copied from the chosen tier at creation time, and its `cycle_anchor_date` is set to the current logical clock. These two status fields are independent axes: the membership axis (`lifecycle_status`, running `DRAFT` → `ACTIVE` → `PAUSED` and ultimately to `CANCELLED`) and the billing-health axis (`billing_status`, running `CURRENT` → `PAST_DUE` → `GRACE` → `LAPSED`) evolve separately and are tracked separately. A pledge also carries `scheduled_tier_id` (the tier queued to take effect at the next anchor for a deferred change, null when none is scheduled), `current_cycle_charged_cents` (the running total billed to the pledge within the current cycle, used to enforce per-creation caps), `grace_deadline`, `lapsed_at`, and `win_back_applied` (a boolean, false by default, recording whether a win-back discount was applied to a reactivation cycle).

Pledge creation does not immediately make the pledge live. For a `MONTHLY` tier under an `UP_FRONT` creator, the system computes the initial proration and creates a `PENDING` charge of kind `INITIAL_PRORATION` (the proration arithmetic and its end-of-month variant are detailed in §3.4 and §3.6). The pledge advances from `DRAFT` to `ACTIVE` only once its first charge settles `SUCCEEDED`; until then it stays `DRAFT`, and a failed first charge leaves it `DRAFT` with `billing_status` set to `PAST_DUE`. When the first charge settles successfully, the pledge's `cycle_anchor_date` is established and `current_cycle_charged_cents` is set to the settled charge amount; the owning tier's `active_pledge_count` is incremented.

A patron may pause an `ACTIVE` pledge, advancing `lifecycle_status` from `ACTIVE` to `PAUSED`. Pausing is permitted only when the pledge is currently `ACTIVE`; otherwise it is rejected with `ERR_PLEDGE_NOT_ACTIVE`. Pausing carries `expected_pledge_version` and is rejected with `ERR_STALE_VERSION` on a version mismatch as described in §2.7. A pause suspends future renewal charges with no refund of the current cycle and increments the pledge's `version` by one. Conversely, resuming a `PAUSED` pledge advances `lifecycle_status` from `PAUSED` back to `ACTIVE`; resuming is permitted only when the pledge is `PAUSED`, otherwise it is rejected with `ERR_PLEDGE_NOT_PAUSED`. Resume re-anchors `cycle_anchor_date` to the current clock cycle so that renewal billing resumes at the next anchor, and increments the pledge's `version` by one.

Cancellation moves a pledge from either `ACTIVE` or `PAUSED` to the terminal `CANCELLED`; an attempt to cancel a pledge in any other lifecycle state is rejected with `ERR_PLEDGE_NOT_CANCELLABLE`. Cancellation has a four-part cascade: the owning tier's `active_pledge_count` is decremented; the pledge's `billing_status` is set to `LAPSED`; `lapsed_at` is set to the current clock and `grace_deadline` is cleared; and, as a cross-entity effect, any `OPEN` conversation between this patron and this creator for which the patron no longer holds any other `ACTIVE` or `PAUSED` pledge is moved to `CLOSED`.

Reactivation is the cyclic re-entry that distinguishes this membership machine: a pledge that is `CANCELLED` on the lifecycle axis and `LAPSED` on the billing axis can loop back to `ACTIVE`. Reactivation is permitted only when both conditions hold — `lifecycle_status` is `CANCELLED` and `billing_status` is `LAPSED` — otherwise it is rejected with `ERR_PLEDGE_NOT_REACTIVATABLE`. On reactivation the pledge's `lifecycle_status` returns to `ACTIVE`, its `billing_status` returns to `CURRENT`, its `cycle_anchor_date` is re-anchored to the current logical clock, its `current_cycle_charged_cents` is reset to 0, its `grace_deadline` is cleared (set null), and the owning tier's `active_pledge_count` is incremented. A `WIN_BACK` charge is created for the reactivation cycle (its amount computed as described in §3.6); if a redeemable win-back offer is applied, `win_back_applied` is set to true and the offer is redeemed.

### 3.3. Billing Health, Renewals, and the Billing Cycle

The billing-health axis tracks whether a pledge's money is flowing. It starts at `CURRENT`. When a `CYCLE_RENEWAL` or `PER_CREATION` charge settles `FAILED`, the system advances `billing_status` from `CURRENT` to `PAST_DUE` and schedules one retry. If that retry charge also settles `FAILED`, `billing_status` advances from `PAST_DUE` to `GRACE`, and a `grace_deadline` is set to the current clock plus a grace window of one week. While in `GRACE`, if a charge settles `SUCCEEDED` before the `grace_deadline` is reached, the pledge's `billing_status` is restored from `GRACE` to `CURRENT` and `grace_deadline` is cleared, returning the member to good standing.

The platform advances time-driven billing by running the billing cycle, an administrative sweep. Each run performs three duties. First, it lapses grace: any pledge in `GRACE` whose `grace_deadline` is at or before the current clock advances on the billing axis from `GRACE` to the terminal `LAPSED`, and this triggers the same cancellation cascade as a manual cancel — the pledge's `lifecycle_status` is moved to `CANCELLED`, the owning tier's `active_pledge_count` is decremented, `lapsed_at` is set — and, in addition, a `WinBackOffer` is auto-created for the freshly lapsed pledge. Second, it expires offers: any `WinBackOffer` still in `OFFERED` whose `expires_at` is now in the past — that is, the current clock has moved beyond `expires_at` — advances to the terminal `EXPIRED` and can no longer be redeemed. Third, it renews: every `ACTIVE` `MONTHLY` pledge whose next cycle anchor — defined as the first day of the calendar month (00:00:00Z) following the pledge's current `cycle_anchor_date` month — is at or before the current clock receives a fresh `PENDING` charge of kind `CYCLE_RENEWAL`, has its `cycle_anchor_date` advanced to that new anchor, and has `current_cycle_charged_cents` reset to 0. The renewal charge's `gross_amount_cents` is the tier's full `monthly_fee_cents` (the new anchor is the first of the month, so the renewal cycle is a full month, not prorated); the renewal proceeds regardless of the pledge's `billing_status`. The run reports the identifiers of the pledges it lapsed, the offers it expired, and the renewal charges it emitted, in a response body carrying the keys `lapsed_pledge_ids`, `expired_offer_ids`, and `renewal_charge_ids` (each an array of UUID strings).

The logical clock that all of this depends on is set explicitly through an administrative clock-setting capability that accepts a target instant `to_iso8601` and reports back the new `current_utc`. At server startup the clock reads exactly `2026-01-01T00:00:00Z` and never falls back to wall-clock time; before any clock-setting call the clock holds precisely this default. Setting the clock advances logical time but does not by itself trigger any sweep — lapsing, expiry, and renewal happen only when the billing cycle is run.

### 3.4. Proration and Charge Timing

When a patron pledges to a `MONTHLY` tier, the first cycle is prorated for the portion of the calendar month that remains. The proration is forward-looking and computed in integer cents, rounded half up. First, take the number of days in the calendar month (UTC) that the cycle anchor falls in. Next, take the day-of-month of the `cycle_anchor_date` in UTC, a value from 1 up to the number of days in that month. The number of remaining days is the days in the month minus one less than the day-of-month — equivalently, the anchor day itself counts as remaining, so an anchor on the first of the month yields a full month of remaining days and an anchor on the last day yields a single remaining day. The base amount for a brand-new pledge is the tier's `monthly_fee_cents`. The prorated charge is the base multiplied by the remaining days, divided by the days in the month, with the result rounded half up to whole cents.

The same proration drives a tier change. When a patron upgrades a pledge to a different tier, the base for the delta is the new tier's `monthly_fee_cents` minus the old tier's `monthly_fee_cents`, and that delta is prorated over the remaining days of the current cycle in exactly the same way.

Charge timing decides when these amounts are actually collected, and it is a dual-variant rule keyed on the creator's `charge_timing`. Under `UP_FRONT`, the prorated amount becomes a charge created `PENDING` immediately at pledge or upgrade time — kind `INITIAL_PRORATION` for a new pledge, kind `UPGRADE_PRORATION` for an upgrade. Under `END_OF_MONTH`, no charge is created immediately and the prorated amount is deferred; the deferred initial proration is not separately materialized as a charge by the billing cycle (the billing-cycle renewal duty in §3.3 emits a full-month `CYCLE_RENEWAL` charge for `ACTIVE` pledges only, and an `END_OF_MONTH` pledge with no immediate first charge therefore remains `DRAFT` until a charge is created against it by another path — for example an admin-created charge — and settles).

The upgrade flow itself moves the pledge's tier and is guarded by optimistic concurrency. An upgrade request carries the target `new_tier_id` and `expected_pledge_version`, and is rejected with `ERR_STALE_VERSION` on a version mismatch per §2.7. Every successful upgrade increments the pledge's `version` by one. Under an `UP_FRONT` creator the upgrade computes the proration delta and creates an `UPGRADE_PRORATION` charge `PENDING`, and the `active_pledge_count` of both the old tier and the new tier is recomputed on this immediate path. Under an `END_OF_MONTH` creator the upgrade creates no immediate charge; instead it records the target tier in `scheduled_tier_id` to take effect at the next cycle anchor.

### 3.5. Charges, Settlement, Refunds, and Wallet Credit

A `Charge` is the unit of money movement against a pledge. Most charges are minted automatically by the pledge, post-publishing, and billing-cycle flows, but a `PlatformAdmin` may also create one directly by supplying the `pledge_id`, the `charge_kind` (one of `INITIAL_PRORATION`, `CYCLE_RENEWAL`, `UPGRADE_PRORATION`, `PER_CREATION`, or `WIN_BACK`), and the `gross_amount_cents` (a non-negative integer, i.e. at least 0; a missing, non-integer, or negative value is rejected with `ERR_INVALID_REQUEST`). Every charge denormalizes its `creator_id` from the pledge for later payout grouping, records the `cycle_anchor_date` of the cycle it belongs to, and starts in `PENDING` status. At creation the patron's wallet credit is applied against the gross to determine the cash actually taken from the card: the `wallet_applied_cents` is the portion of the patron's `wallet_credit_cents` consumed against this charge, bounded between zero and `gross_amount_cents`, and the `net_amount_cents` is the gross minus the wallet applied. A charge also carries `processing_fee_cents`, computed at settlement, and `swept_into_payout_id`, the payout that later sweeps it (null until swept).

Settling a charge is a `PlatformAdmin` action that supplies an `outcome` and drives the charge out of `PENDING`. The settle is permitted only when the charge is `PENDING`; otherwise it is rejected with `ERR_CHARGE_NOT_PENDING`. When the outcome is success, the charge moves from `PENDING` to `SUCCEEDED`, and several effects fire together: the processing fee is computed and stored (per §3.7); the pledge's `current_cycle_charged_cents` is increased by the charge's `gross_amount_cents`; the creator's `pending_payout_cents` is increased by the charge's `net_amount_cents`; and if this is the pledge's first charge, the pledge bubbles from `DRAFT` to `ACTIVE`. A successful settlement of a charge while the pledge is in `GRACE` restores the pledge's `billing_status` to `CURRENT` as described in §3.3. When the outcome is failure, the charge moves from `PENDING` to `FAILED`, the `wallet_applied_cents` that had been consumed is refunded back into the patron's `wallet_credit_cents` so that wallet value is conserved, and the failure drives the pledge's billing axis forward through `PAST_DUE` and, on a failed retry, to `GRACE`.

A creator may refund one of its own charges, moving it from `SUCCEEDED` to the terminal `REFUNDED`. A refund is permitted only when the charge is `SUCCEEDED`; a charge in any other state is rejected with `ERR_CHARGE_NOT_REFUNDABLE`. A charge that has already been swept into a payout cannot be refunded — its `swept_into_payout_id` must still be null — and a swept charge is rejected with `ERR_CHARGE_ALREADY_SWEPT`. Refunding returns the charge's `net_amount_cents` to the patron's `wallet_credit_cents`, decreases the creator's `pending_payout_cents` by that same `net_amount_cents` (conserving the pending balance), and decreases the pledge's `current_cycle_charged_cents` by the charge's `gross_amount_cents`.

### 3.6. Per-Creation Charges and Win-Back Reactivation

Creators on the `PER_CREATION` model bill their patrons when they publish paid creations rather than on a monthly rhythm. A `Post` is authored with the `creator_id`, a `title`, a `body`, an optional `min_tier_rank` (a non-negative integer, defaulting to a value that makes the post public, where 0 means anyone can view it), and an optional `is_paid_creation` boolean (false by default). A post is born in `DRAFT` and is moved to `PUBLISHED` by its creator. Publishing a paid creation under a per-creation creator triggers billing: for each eligible pledge — one that is `ACTIVE`, whose `billing_model` is `PER_CREATION`, and that sits on a qualifying tier for this creator's published paid post — the system computes a per-creation charge. A paid-creation publish is only meaningful for the per-creation model; attempting it where the creator's or tier's billing model is not `PER_CREATION` is rejected with `ERR_BILLING_MODEL_MISMATCH`.

The per-creation charge respects each pledge's monthly cap and is computed from at least three inputs. First, determine the remaining cap for the pledge: it is the tier's `per_creation_monthly_cap_cents` minus the pledge's `current_cycle_charged_cents`, floored at zero so it is never negative. The charge amount is then the smaller of the tier's `per_creation_fee_cents` and that remaining cap. If the charge amount works out to zero — the cap is already exhausted for this cycle — no charge row is created for that pledge this cycle; this is the normal, non-error outcome of a full cap. When a charge is created it is a `PER_CREATION` charge in `PENDING`. Creating each such per-creation charge immediately raises the pledge's `current_cycle_charged_cents` by the charge amount at creation time — independently of, and prior to, any later settlement — so that consecutive paid-creation publishes within the same cycle see the accumulated total and the cap formula above is enforced cumulatively across them; a publish that creates no charge (full cap) leaves the running total unchanged.

Win-back is the program for recovering lapsed patrons. When a pledge lapses, the platform makes a `WinBackOffer` available — automatically during the billing-cycle lapse, or explicitly when a creator or admin creates one against a lapsed pledge by supplying the `pledge_id` and an optional `discount_pct`. The discount is a fraction strictly greater than 0 and strictly less than 1, defaulting to 0.30, that applies to the reactivation cycle's first charge. An offer is born in `OFFERED` status; its `expires_at` is computed as the pledge's `lapsed_at` plus a win-back window of 60 days (UTC). Explicit offer creation does not enforce that the target pledge is actually lapsed: an offer may be created against any existing pledge, and if the pledge's `lapsed_at` is null the offer's `expires_at` is set to null (and such an offer, lacking an `expires_at`, is never redeemable). An offer is redeemable only while its `status` is `OFFERED` and the current clock is at or before its `expires_at`.

When a patron reactivates, the first charge of the new cycle — kind `WIN_BACK` — is computed with the evaluation order pinned: prorate first, then discount the prorated base. Begin by prorating the tier's `monthly_fee_cents` over the remaining days of the cycle exactly as in §3.4, rounded half up. If a redeemable win-back offer exists for the pledge — one whose `status` is `OFFERED` and whose `expires_at` is at or after the current clock — take its `discount_pct` and redeem it; otherwise the discount is zero. The charge's `gross_amount_cents` is then the prorated amount multiplied by one minus the discount fraction, rounded half up to whole cents. This prorate-then-discount order is canonical; reversing it would yield a different cent value. Reactivation does not itself fail on the absence of a redeemable offer: if the pledge has no offer, or its only offer is not redeemable (already `REDEEMED` or `EXPIRED`, or still `OFFERED` but past its `expires_at` window), the reactivation simply proceeds with discount zero — it is not rejected, and any such non-redeemable offer is left untouched in its current status. When a redeemable offer is redeemed it advances from `OFFERED` to the terminal `REDEEMED`; when the billing cycle finds an `OFFERED` offer past its `expires_at` it advances to the terminal `EXPIRED`.

### 3.7. Processing Fees, Pending Earnings, and Payouts

Every successful charge carries a payment-processor fee, computed when the charge settles `SUCCEEDED`. If the charge's `net_amount_cents` is zero — the wallet covered the whole gross — the `processing_fee_cents` is zero. Otherwise the fee is the `net_amount_cents` multiplied by a percentage rate of 0.029, rounded half up to whole cents, plus a flat 30 cents. This fee is rounded per individual charge at settlement time; the rounding happens per line, before any later summation, and a payout must never re-derive a fee from a summed gross, because summing-then-rounding would diverge by cents.

A creator's `pending_payout_cents` is the running net of its settled, unswept earnings — precisely the sum of `net_amount_cents` over every charge of the creator whose `status` is `SUCCEEDED` and whose `swept_into_payout_id` is still null. The platform maintains it incrementally: a successful settlement adds the charge's net, a refund subtracts it, and a payout reversal adds it back. It begins at zero and is recomputed on each of those events.

A payout sweeps a creator's earnings for one cycle into a single settlement. A `PlatformAdmin` initiates a sweep by supplying the `creator_id` and the `cycle_anchor_date` to be swept. The sweep selects every charge belonging to that creator whose `status` is `SUCCEEDED`, whose `swept_into_payout_id` is null, and whose `cycle_anchor_date` equals the requested one, processed in ascending order of each charge's `created_at`. If no charge matches, no payout is created and the request is rejected with `ERR_NOTHING_TO_PAYOUT`. Otherwise a `Payout` is created in `PENDING` with these computed totals: `gross_cents` is the sum of `net_amount_cents` over the swept charges; `processing_fee_cents` is the sum of the already-rounded per-line `processing_fee_cents` of those charges; `platform_fee_cents` is the `gross_cents` multiplied by the commission rate for the creator's `platform_plan` — 0.10 for `STARTER`, 0.08 for `PRO`, and 0.05 for `PREMIUM` — rounded half up once over the whole gross; and `payout_amount_cents` is the `gross_cents` minus the `platform_fee_cents` minus the `processing_fee_cents`. The `swept_charge_count` records how many charges were swept. Each swept charge has its `swept_into_payout_id` set to the new payout, and the creator's `pending_payout_cents` is reduced by the total net that was swept.

A pending payout can be marked paid or reversed, each a `PlatformAdmin` action. Marking paid moves the payout from `PENDING` to the terminal `PAID` and is permitted only from `PENDING`; otherwise it is rejected with `ERR_PAYOUT_NOT_PENDING`. Reversing moves the payout from `PENDING` to the terminal `REVERSED` and is permitted only from `PENDING`; otherwise it is rejected with `ERR_PAYOUT_NOT_REVERSIBLE`. A reversal un-sweeps: every charge that had been swept into the payout has its `swept_into_payout_id` cleared, and the creator's `pending_payout_cents` is increased by the sum of the `net_amount_cents` of those charges, restoring the balance that the sweep had removed and keeping pending earnings conserved across the sweep-then-reverse pair.

### 3.8. Exclusive Content Access and Patron-Only Messaging

Posts are gated by tier. A patron requests access to a published post by supplying its `patron_id`; the post must be `PUBLISHED` (a request against a non-`PUBLISHED` post is rejected with `ERR_POST_NOT_FOUND`), and the gate admits the patron only when the patron holds an `ACTIVE` pledge to the post's creator on a tier whose `rank` is at least the post's `min_tier_rank`. Posts with a `min_tier_rank` of 0 are public and admit any patron. A patron whose active tier rank falls below the post's `min_tier_rank` is rejected with `ERR_TIER_TOO_LOW`. When the gate passes, the system mints an immutable `PostAccess` grant recording the `post_id`, the requesting `patron_id`, the `pledge_id` that granted access at grant time, and `granted_tier_rank`, a snapshot of the patron's tier rank at the instant access was granted. When multiple `ACTIVE` pledges to the creator exist, the highest-ranked one is the granting pledge and its rank is the snapshot. For a public post (`min_tier_rank` 0) where the patron holds no `ACTIVE` pledge to the creator, the grant is still minted with `pledge_id` set to null and `granted_tier_rank` set to 0. Because a `PostAccess` grant references its post, patron, and granting pledge, the grant list can be filtered by `post_id`, `patron_id`, or `pledge_id` for reverse lookup.

Messaging between a patron and a creator is private and gated on active membership. A `Conversation` is opened by supplying the `creator_id` and `patron_id`; it begins `OPEN` with `message_count` initialized to 0. When a patron opens a conversation or sends a message, the patron must hold a pledge to that creator whose `lifecycle_status` is `ACTIVE` or `PAUSED`; a patron without such a pledge is rejected with `ERR_NOT_A_PATRON_OF_CREATOR`. A `Message` is posted by supplying the `conversation_id` and the `body`; the server derives `sender_role` (`CREATOR` or `PATRON`) and `sender_id` from the auth context, and the conversation it targets must match the sender's side. Because the sender's side is the acting principal's own `id`, this matching is enforced as the ownership check from §2.1: a `Creator` whose `id` is not the conversation's `creator_id`, or a `Patron` whose `id` is not the conversation's `patron_id`, is rejected with `ERR_NOT_RESOURCE_OWNER` (the `ERR_CROSS_LINK_MISMATCH` outcome is not reached on this path). Each posted message increments the conversation's `message_count` by one. Messages may be posted only to an `OPEN` conversation; posting to, or closing, a conversation that is already `CLOSED` is rejected with `ERR_CONVERSATION_CLOSED`. A conversation can be closed explicitly, moving it from `OPEN` to the terminal `CLOSED`, after which no further messages may be posted; it is also closed automatically when a patron's last `ACTIVE` or `PAUSED` pledge to the creator is cancelled, as described in §3.2.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify an existing resource (including state transitions and the administrative clock and billing operations) return `200 OK`. List and retrieval operations return `200 OK`. Request bodies, response shapes, and side effects for each endpoint are specified in the §3 narratives; the table below is the routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/creators` | Register a creator | Creator |
| GET | `/creators` | List creators | Creator, Patron, PlatformAdmin |
| GET | `/creators/{creatorId}` | Get a creator | Creator, Patron, PlatformAdmin |
| POST | `/tiers` | Create a tier (DRAFT) for a creator | Creator |
| GET | `/tiers` | List tiers; filter by `creator_id`, `status` | Creator, Patron, PlatformAdmin |
| GET | `/tiers/{tierId}` | Get a tier | Creator, Patron, PlatformAdmin |
| POST | `/tiers/{tierId}/publish` | Publish a DRAFT tier | Creator |
| POST | `/tiers/{tierId}/retire` | Retire a PUBLISHED tier | Creator |
| POST | `/patrons` | Register a patron | Patron |
| GET | `/patrons/{patronId}` | Get a patron | Creator, Patron, PlatformAdmin |
| POST | `/pledges` | Create a pledge | Patron |
| GET | `/pledges` | List pledges; filter by `patron_id`, `creator_id`, `tier_id`, `scheduled_tier_id`, `lifecycle_status` | Creator, Patron, PlatformAdmin |
| GET | `/pledges/{pledgeId}` | Get a pledge | Creator, Patron, PlatformAdmin |
| POST | `/pledges/{pledgeId}/pause` | Pause an ACTIVE pledge | Patron |
| POST | `/pledges/{pledgeId}/resume` | Resume a PAUSED pledge | Patron |
| POST | `/pledges/{pledgeId}/upgrade` | Change a pledge's tier | Patron |
| POST | `/pledges/{pledgeId}/cancel` | Cancel an ACTIVE/PAUSED pledge | Patron |
| POST | `/pledges/{pledgeId}/reactivate` | Reactivate a CANCELLED+LAPSED pledge | Patron |
| POST | `/charges` | Create a charge against a pledge | PlatformAdmin |
| GET | `/charges` | List charges; filter by `pledge_id`, `creator_id`, `status`, `cycle_anchor_date`, `swept_into_payout_id` | Creator, Patron, PlatformAdmin |
| GET | `/charges/{chargeId}` | Get a charge | Creator, Patron, PlatformAdmin |
| POST | `/charges/{chargeId}/settle` | Settle a PENDING charge | PlatformAdmin |
| POST | `/charges/{chargeId}/refund` | Refund a SUCCEEDED, unswept charge | Creator |
| POST | `/posts` | Create a DRAFT post | Creator |
| GET | `/posts` | List posts; filter by `creator_id`, `status` | Creator, Patron, PlatformAdmin |
| GET | `/posts/{postId}` | Get a post (metadata only) | Creator, Patron, PlatformAdmin |
| POST | `/posts/{postId}/publish` | Publish a DRAFT post | Creator |
| POST | `/posts/{postId}/access` | Request access to a post | Patron |
| GET | `/post-accesses` | List PostAccess grants; filter by `post_id`, `patron_id`, `pledge_id` | Creator, Patron, PlatformAdmin |
| GET | `/post-accesses/{accessId}` | Get a single PostAccess grant | Creator, Patron, PlatformAdmin |
| POST | `/conversations` | Open a conversation | Patron, Creator |
| GET | `/conversations` | List conversations; filter by `creator_id`, `patron_id`, `status` | Creator, Patron, PlatformAdmin |
| GET | `/conversations/{conversationId}` | Get a conversation | Creator, Patron, PlatformAdmin |
| POST | `/conversations/{conversationId}/close` | Close an OPEN conversation | Creator, Patron |
| POST | `/messages` | Post a message to an OPEN conversation | Patron, Creator |
| GET | `/messages` | List messages; filter by `conversation_id` | Creator, Patron, PlatformAdmin |
| GET | `/messages/{messageId}` | Get a single message | Creator, Patron, PlatformAdmin |
| POST | `/payouts` | Sweep a creator's charges into a PENDING payout | PlatformAdmin |
| GET | `/payouts` | List payouts; filter by `creator_id`, `status` | Creator, PlatformAdmin |
| GET | `/payouts/{payoutId}` | Get a payout | Creator, PlatformAdmin |
| POST | `/payouts/{payoutId}/mark-paid` | Mark a PENDING payout PAID | PlatformAdmin |
| POST | `/payouts/{payoutId}/reverse` | Reverse a PENDING payout | PlatformAdmin |
| POST | `/win-back-offers` | Create a win-back offer for a lapsed pledge | Creator, PlatformAdmin |
| GET | `/win-back-offers` | List win-back offers; filter by `pledge_id`, `status` | Creator, Patron, PlatformAdmin |
| GET | `/win-back-offers/{offerId}` | Get a win-back offer | Creator, Patron, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/_billing/run-cycle` | Run the billing cycle | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_CREATOR_NOT_FOUND` | 404 Not Found |
| `ERR_TIER_NOT_FOUND` | 404 Not Found |
| `ERR_PATRON_NOT_FOUND` | 404 Not Found |
| `ERR_PLEDGE_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGE_NOT_FOUND` | 404 Not Found |
| `ERR_POST_NOT_FOUND` | 404 Not Found |
| `ERR_CONVERSATION_NOT_FOUND` | 404 Not Found |
| `ERR_PAYOUT_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_TIER_FIELDS_INCOMPLETE` | 400 Bad Request |
| `ERR_TIER_NOT_PUBLISHED` | 409 Conflict |
| `ERR_TIER_HAS_MEMBERS` | 409 Conflict |
| `ERR_PLEDGE_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLEDGE_NOT_PAUSED` | 409 Conflict |
| `ERR_PLEDGE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PLEDGE_NOT_REACTIVATABLE` | 409 Conflict |
| `ERR_CHARGE_NOT_PENDING` | 409 Conflict |
| `ERR_CHARGE_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_CHARGE_ALREADY_SWEPT` | 409 Conflict |
| `ERR_CONVERSATION_CLOSED` | 409 Conflict |
| `ERR_PAYOUT_NOT_PENDING` | 409 Conflict |
| `ERR_PAYOUT_NOT_REVERSIBLE` | 409 Conflict |
| `ERR_OFFER_NOT_REDEEMABLE` | 409 Conflict |
| `ERR_CROSS_LINK_MISMATCH` | 409 Conflict |
| `ERR_TIER_RANK_TAKEN` | 409 Conflict |
| `ERR_DUPLICATE_PLEDGE` | 409 Conflict |
| `ERR_NOT_A_PATRON_OF_CREATOR` | 403 Forbidden |
| `ERR_TIER_TOO_LOW` | 403 Forbidden |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_BILLING_MODEL_MISMATCH` | 409 Conflict |
| `ERR_NOTHING_TO_PAYOUT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
