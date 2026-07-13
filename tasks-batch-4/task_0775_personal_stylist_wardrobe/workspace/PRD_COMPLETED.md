# Personal Stylist & Wardrobe API — Product Requirements Document

## 1. Introduction

Personal styling is a high-touch service business in which a stylist and a client work together across closet audits, shopping trips, virtual consultations, and event preparation. The commercial reality behind that relationship is surprisingly intricate: time is billed by the quarter-hour, some clients prepay a finite block of hours while others pay as they go, retail purchases carry a tiered markup that splits into a stylist commission, and seasonal subscriptions and word-of-mouth referrals feed store credit back to clients. This API is the system of record for all of it.

The platform is organized around the **engagement** — the working relationship between one client and one stylist — which acts as the hub aggregate that owns sessions, lookbooks, and invoices. Around that hub sit peer entities: clients and stylists as the two human parties, subscriptions that grant seasonal-refresh privileges, and referrals that reward clients for bringing in new business. The system must keep several running ledgers perfectly reconciled at all times — a prepaid package's block accounting, an engagement's retail spend, a stylist's earned commission, and each client's wallet credit balance — because those figures drive both what a client is billed and what a stylist is paid.

This document specifies the entities, their lifecycles, the pricing calculations, and the validation and authorization rules that govern the API. It is written for the engineers who will implement the service and is intended to be complete: every field, transition, and monetary rule a correct implementation must honor is described here.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and conventions that apply across every endpoint. The whole API is mounted under the `/styling` path prefix (with the sole exception of the operational clock endpoint).

### 2.1. User and Role-Based Access Control

Every request other than client self-registration and the clock control endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing or malformed on these headers is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes four roles, spelled exactly `Anonymous`, `Client`, `Stylist`, and `PlatformAdmin`.

- When `X-User-Role` is `Anonymous`, the caller is unauthenticated and `X-User-ID` is an opaque, non-persisted value; the only operation permitted is self-registering a new client.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign key to `X-User-ID`. A `Client` may act only on engagements it owns (the engagement's `client_id` equals `X-User-ID`), on the sessions, lookbooks, and invoices under those engagements, on its own subscriptions (the subscription's `client_id` equals `X-User-ID`), and on referrals it authored (the referral's `referrer_client_id` equals `X-User-ID`).
- When `X-User-Role` is `Stylist`, `X-User-ID` is the `id` of the acting `Stylist`; ownership checks compare an engagement's `stylist_id` to `X-User-ID`. A `Stylist` may act only on sessions, purchase items, and lookbooks belonging to engagements whose `stylist_id` equals `X-User-ID`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it operationally but does not compare it to any entity's `id`; a `PlatformAdmin` is an operational superuser for provisioning, billing issuance, wallet adjustments, referral signup, subscription activation, and the logical clock.

An `entity_backed` principal (a `Client` or a `Stylist`) that is authenticated but attempts to act on a resource it does not own is rejected with `ERR_UNAUTHORIZED` (HTTP 403) — the same code used for a disallowed role.

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

List endpoints are paginated with two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0. Out-of-range values are clamped rather than rejected: a `limit` below 1 becomes 1 and above 100 becomes 100, and a negative `offset` becomes 0; a non-integer `limit` or `offset` falls back to its default.

Unless a specific endpoint says otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every entity in this system is a common-fielded resource: each carries a server-minted `id` (a UUID with no type prefix), a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. The `created_at` and `updated_at` values are ISO 8601 UTC timestamps with three fractional digits. The `version` starts at 1 on creation and increments by one on every mutation of the resource; `updated_at` is refreshed on every such mutation. Because derived fields (ledger balances, block counts, running commission and spend totals) are stored on their owning entity, any change to those derived fields is itself a mutation that bumps `version` and refreshes `updated_at` on that entity.

### 2.5. Monetary Values, Blocks, and Rounding

All money in the system is expressed in integer **cents**. Where a calculation multiplies cents by a fractional rate, the result is rounded to whole cents using the **round half up** convention (a fractional half-cent rounds away from zero). Each monetary output named in this document is rounded independently at the point the formula specifies; the document is explicit wherever the order of rounding is load-bearing.

Billable time is measured in **15-minute blocks**. A session always bills at least four blocks — a one-hour floor — regardless of how short the scheduled or actual duration is. Block counts are exact integers and are never rounded as money; only the conversion from minutes to blocks rounds, and it always rounds a partial block up to a whole block.

### 2.6. Optimistic Concurrency on Prepaid Packages

Scheduling a session under an engagement is guarded by optimistic concurrency control on the engagement. The schedule-a-session request must include `expected_engagement_version`, carrying the client's last observed `version` of the target engagement. This field is mandatory on that request and is not accepted on any other endpoint. When the request is processed, the supplied `expected_engagement_version` is compared against the engagement's current `version` as the final check, after every other validation has passed. If they do not match — because a prior successful schedule call already reserved blocks from the finite prepaid pool and advanced the engagement's `version` since the client last read it — the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412) and no reservation is made. This prevents a client working from a stale view of remaining availability from overwriting blocks it never observed.

### 2.7. Reconciled Ledgers and Their Invariants

The system maintains four running totals that must stay reconciled with the transactions that feed them:

- A PACKAGE engagement's block ledger tracks `hours_reserved_blocks` (blocks held by sessions that are `SCHEDULED` or `CONFIRMED` but not yet consumed), `hours_consumed_blocks` (blocks permanently used by `COMPLETED` sessions), and `hours_available_blocks`. The available figure is always the prepaid `package_blocks` minus reserved minus consumed, and the conservation invariant holds after every mutation: `package_blocks` always equals the sum of available, reserved, and consumed blocks.
- Each engagement's `retail_spend_cents` always equals the sum of `marked_up_price_cents` over its purchase items currently in `PURCHASED` status.
- Each stylist's `earned_commission_cents` is the running total of `commission_cents` across all still-`PURCHASED` items on that stylist's engagements.
- Each client's `wallet_credit_cents` is a store-credit balance, credited by referral rewards and admin adjustments and debited by subscription activation fees and invoice payment. It may never be negative.

Every operation that touches one of these totals adjusts it immediately and in the same transaction as the triggering event, and returns the affected quantities to their pre-event values on reversal (session cancellation, item return, engagement cancellation).

### 2.8. Cascading State Propagation

Several operations mutate more than one entity. When a completing session exhausts a prepaid package, the engagement is driven to its fulfilled state automatically and a lookbook is auto-created — the server performs these parent transitions without a separate client request. Likewise, paying an invoice can automatically qualify a referral and credit a referrer's wallet. Each entity touched by such a cascade is independently mutated: its `version` increments and its `updated_at` is refreshed. The specific cascades are described in §3 alongside the workflows that trigger them.

### 2.9. Nested Resource Retrieval

Many resources are addressed under a parent path (for example, sessions and lookbooks and invoices under an engagement, or assessments and subscriptions under a client). For any request whose path names more than one resource, the identifiers are validated left to right, and the first one that does not resolve produces that resource's own not-found error before any deeper resource is consulted — a session request under a non-existent engagement fails with `ERR_ENGAGEMENT_NOT_FOUND`, not `ERR_SESSION_NOT_FOUND`. The not-found codes are `ERR_CLIENT_NOT_FOUND`, `ERR_STYLIST_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_PURCHASE_ITEM_NOT_FOUND`, `ERR_LOOKBOOK_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, and `ERR_INVOICE_NOT_FOUND`, each returning HTTP 404. When a foreign key supplied in a request body (such as `client_id`, `stylist_id`, `referrer_client_id`, or `referee_client_id`) does not resolve to an existing entity, the same not-found family applies.

### 2.10. The Logical Clock and Time Windows

All expiry, period, and window rules read a server-maintained logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z` and never falls back to real time; a `PlatformAdmin` may advance it by supplying a `to_iso8601` instant to the clock control endpoint. Subscription periods, referral expiry, and invoice payment timestamps are all stamped from this clock.

### 2.11. Validation Ordering

When several checks guard one endpoint, they are evaluated in a fixed order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_UNAUTHORIZED`), then existence of every resource named in the path (the not-found family), then resolution of foreign keys in the body (the not-found family), then ownership by the acting principal (`ERR_UNAUTHORIZED`), then body well-formedness (`ERR_VALIDATION`, including `ERR_INVALID_TIME_RANGE` for a bad time window), then the target's state eligibility for the requested transition (the invalid-state family). Business-specific checks follow the general checks. For the schedule-a-session endpoint in particular, after the general checks the stylist-overlap check runs, then the client-buffer check, then the package-availability check, and the optimistic-concurrency version check runs last of all. The specific business errors and the workflows they guard are described in §3.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Clients, Stylists, and the Style Assessment

A prospective client joins by self-registering with a `full_name` and an `email`; the email must be unique across clients, and a registration whose email duplicates an existing client's is rejected with `ERR_VALIDATION`. Registration creates a `Client` in `ACTIVE` status with `wallet_credit_cents` starting at 0 and `has_paid_invoice` starting false. All registered clients are `ACTIVE` — there is no suspension workflow — and the same is true of stylists. A `PlatformAdmin` provisions each stylist with a `full_name`, a unique `email` (a duplicate stylist email is likewise rejected with `ERR_VALIDATION`), a `commission_pct` (a fraction between 0 and 1 inclusive, representing the share of each item's markup margin the stylist earns), and a seniority `tier` of `JUNIOR`, `SENIOR`, or `LEAD` (informational only; it does not affect pricing). A newly created stylist is `ACTIVE` with `earned_commission_cents` at 0. Fetching a stylist exposes `earned_commission_cents`; fetching a client exposes `wallet_credit_cents` and `has_paid_invoice`.

Before any real styling work can be confirmed, the client's taste must be captured. A `Client` opens a **style assessment** against its own client record, supplying a free-text `body_type`, a seasonal `color_palette` of `WARM`, `COOL`, or `NEUTRAL`, a `budget_band` of `ECONOMY`, `MID`, `PREMIUM`, or `LUXURY`, and free-text `lifestyle` notes. The assessment is created in `DRAFT`. The owning client is recorded via the assessment's `client_id`. A `Stylist` later finalizes the profile, moving it from `DRAFT` to `COMPLETED`; completing an assessment that is not currently `DRAFT` is rejected with `ERR_INVALID_ASSESSMENT_STATE`. A `COMPLETED` assessment for the client is a precondition for confirming that client's sessions, as described in §3.3.

### 3.2. Opening and Governing an Engagement

The working relationship is captured by an **engagement**, opened by a `Client` who supplies `client_id`, `stylist_id`, a billing `mode`, and a per-block price `block_rate_cents` (which must be greater than zero). The mode is either `HOURLY`, where each session's time is billed as line items on the eventual invoice, or `PACKAGE`, where the client prepays a finite pool of blocks that sessions reserve and consume. When the mode is `PACKAGE`, the request must include `package_blocks` (the prepaid pool, which must be at least 4) and may include the informational `package_price_cents` (the prepaid amount, not re-billed); when the mode is `HOURLY`, `package_blocks` must be omitted. A request that supplies `package_blocks` for an `HOURLY` engagement, or omits it for a `PACKAGE` engagement, is rejected as a malformed body with `ERR_VALIDATION`. Both the referenced client and stylist must exist, and the acting client must be the owner.

A new engagement is created in `DRAFT`. For a `PACKAGE` engagement the block ledger is initialized so that `hours_available_blocks` equals `package_blocks` while `hours_reserved_blocks` and `hours_consumed_blocks` are 0. The client activates the engagement, moving it from `DRAFT` to `ACTIVE`; sessions may only be scheduled against an `ACTIVE` engagement. The client may also cancel an engagement from either `DRAFT` or `ACTIVE`, moving it to the terminal `CANCELLED` state. Cancellation cascades: every session under the engagement that is still `SCHEDULED` or `CONFIRMED` is set to `CANCELLED`, and for a `PACKAGE` engagement each such session's reserved blocks are released back to availability (its `estimated_blocks` are subtracted from `hours_reserved_blocks` and added to `hours_available_blocks`). Sessions already `COMPLETED` and their purchase items are left untouched. Attempting a transition the engagement's current state does not permit is rejected with `ERR_INVALID_ENGAGEMENT_STATE`. An engagement also reaches the terminal `FULFILLED` state automatically, as described in §3.4. Fetching an engagement exposes its block ledger, `retail_spend_cents`, and `version`. Engagements can be listed and filtered by `client_id`, `stylist_id`, and `status`.

### 3.3. Scheduling Sessions and Confirmation

A `Client` schedules a **session** under an `ACTIVE` engagement, which supplies the acting stylist and client for the checks below. The request carries a `session_type` — one of `CLOSET_AUDIT`, `SHOPPING`, `VIRTUAL`, or `EVENT` — a `scheduled_start` and a `scheduled_end` (ISO 8601 UTC instants), and the `expected_engagement_version` described in §2.6. The `scheduled_end` must be strictly later than `scheduled_start`; otherwise the request fails with `ERR_INVALID_TIME_RANGE`. The engagement must be `ACTIVE`, or the schedule is rejected with `ERR_INVALID_ENGAGEMENT_STATE`.

On a successful schedule the system computes `estimated_blocks` from the planned window: it takes the whole minutes between `scheduled_start` and `scheduled_end`, divides by fifteen and rounds any partial block up to a whole block, and takes the greater of that figure and four. The provisional `charge_cents` is then `estimated_blocks` multiplied by the engagement's `block_rate_cents`, and the session's `charge_variant` is `PROVISIONAL`. A newly scheduled session is in `SCHEDULED` status. For a `PACKAGE` engagement the scheduling reserves the session's `estimated_blocks`: they are added to `hours_reserved_blocks` and subtracted from `hours_available_blocks`, and the engagement's `version` is incremented by one.

A `Stylist` confirms a session, moving it from `SCHEDULED` to `CONFIRMED`. Confirmation requires the engagement's client to hold a `StyleAssessment` in `COMPLETED` status; if none exists, the confirm is rejected with `ERR_ASSESSMENT_NOT_COMPLETED`. Confirming a session that is not currently `SCHEDULED` is rejected with `ERR_INVALID_SESSION_STATE`. Fetching a session exposes `estimated_blocks`, `charge_cents`, and `charge_variant`; sessions under an engagement may be listed and filtered by `status`.

### 3.4. Rescheduling, Completing, and Cancelling Sessions

A session's `modality` distinguishes an `IN_PERSON` visit from a `VIRTUAL` one; it defaults to `IN_PERSON` when omitted. Two overlap rules protect the calendar, and both are enforced at scheduling time and again at rescheduling time.

The first is the **stylist overlap** rule: the new or rescheduled window `[scheduled_start, scheduled_end)` must not overlap any other non-terminal session (one that is `SCHEDULED` or `CONFIRMED`) belonging to any engagement of the same stylist. Intervals are half-open, so two sessions that merely touch at an endpoint — one ending exactly when the next begins — do not conflict. A violation returns `ERR_STYLIST_TIME_CONFLICT`. The second is the **client travel-buffer** rule, which applies only to `IN_PERSON` sessions: the window expanded by sixty minutes on each side must not overlap any other non-terminal `IN_PERSON` session of the same client, so consecutive in-person sessions for one client need at least a sixty-minute gap between them and mere adjacency is not enough. A violation returns `ERR_CLIENT_TIME_CONFLICT`. `VIRTUAL` sessions are exempt from the client buffer but are still subject to the stylist-overlap rule. When a session is rescheduled, both overlap checks are re-run against the new window while ignoring the session being moved.

A `Client` or a `Stylist` may reschedule a session that is `SCHEDULED` or `CONFIRMED`, supplying a fresh `scheduled_start` and `scheduled_end`; the session returns to `SCHEDULED` status and its `estimated_blocks` and provisional `charge_cents` are recomputed. The new end must again be strictly after the new start. For a `PACKAGE` engagement, if the recomputed `estimated_blocks` differ, the reservation is adjusted by the delta and must still satisfy availability. Rescheduling a session in any other state is rejected with `ERR_INVALID_SESSION_STATE`.

A `Stylist` completes a session that is `CONFIRMED`, supplying `actual_minutes`, which must be present and greater than zero. Completion recomputes the final `charge_cents` from the actual elapsed time: the billable blocks are the greater of four and the whole minutes divided by fifteen rounded up, and the charge is those billable blocks multiplied by `block_rate_cents`. The `charge_variant` becomes `FINAL`, which may differ from the provisional charge when the actual duration lands in a different block count than the plan. The session moves to the terminal `COMPLETED` state. Completing a session that is not `CONFIRMED`, or completing without a positive `actual_minutes`, is rejected with `ERR_INVALID_SESSION_STATE`.

Completion drives a cascade for a `PACKAGE` engagement. First, the session's originally reserved `estimated_blocks` are removed from `hours_reserved_blocks`, the actual billable blocks are added to `hours_consumed_blocks`, and `hours_available_blocks` is recomputed. Then, if after that consumption `hours_available_blocks` has reached 0 and no sibling session under the engagement remains `SCHEDULED` or `CONFIRMED`, the engagement transitions automatically from `ACTIVE` to `FULFILLED`. That fulfillment in turn auto-creates one lookbook in `DRAFT` titled "Final Lookbook" under the engagement, ready for outfit delivery.

A `Client` or a `Stylist` may cancel a session that is `SCHEDULED` or `CONFIRMED`, moving it to the terminal `CANCELLED` state. For a `PACKAGE` engagement, cancellation releases the session's `estimated_blocks` — subtracting them from `hours_reserved_blocks` and adding them to `hours_available_blocks` — so the conservation invariant of §2.7 is restored. Cancelling a session in any other state is rejected with `ERR_INVALID_SESSION_STATE`.

For a `PACKAGE` engagement, scheduling or rescheduling additionally requires that `hours_available_blocks` be at least the requested session's `estimated_blocks`; when the pool cannot cover the reservation the request is rejected with `ERR_INSUFFICIENT_PACKAGE_HOURS`.

### 3.5. Shopping Sessions: Purchases, Markup, and Commission

During a session, a `Stylist` records each **purchase item** the client buys. An item may be recorded only while its session is `CONFIRMED` and its `session_type` is `SHOPPING`; otherwise the request is rejected with `ERR_INVALID_SESSION_STATE`. The stylist supplies a `description` and the raw `retail_cost_cents` (which must be greater than zero), and the item links to its session via `session_id`. The item is created in `PURCHASED` status.

Recording an item computes three derived figures. The markup fraction `markup_pct` is selected by retail band: a retail cost below 5000 cents takes a thirty-percent markup, a cost of at least 5000 cents but below 20000 cents takes a twenty-percent markup, and a cost of 20000 cents or more takes a ten-percent markup. The `marked_up_price_cents` — what the client is billed for the item — is the retail cost multiplied by one plus the markup fraction, rounded half up to whole cents. The `commission_cents` — the stylist's cut of the markup margin — is the difference between the marked-up price and the retail cost, multiplied by that stylist's `commission_pct`, rounded half up to whole cents independently of the price rounding. Recording the item then advances two ledgers forward: the engagement's `retail_spend_cents` increases by the item's `marked_up_price_cents`, and the stylist's `earned_commission_cents` increases by the item's `commission_cents`.

A `Stylist` may return an item that is `PURCHASED`, moving it to the terminal `RETURNED` state; returning an item that is not currently `PURCHASED` is rejected as an invalid state transition with `ERR_INVALID_PURCHASE_ITEM_STATE` (HTTP 409). A return reverses both ledgers: the engagement's `retail_spend_cents` is reduced by the item's `marked_up_price_cents` and the stylist's `earned_commission_cents` is reduced by the item's `commission_cents`, returning both conserved totals to their pre-purchase values. Items under a session may be listed and filtered by `status`.

### 3.6. Lookbooks and Outfit Delivery

A **lookbook** is the styled deliverable of an engagement. A `Stylist` creates a lookbook under an engagement with a `title`; the engagement must be `ACTIVE` or `FULFILLED`. A lookbook begins in `DRAFT` with an empty `outfits` array, an `outfit_count` of 0, and a `revision_round` of 0, and records its parent via `engagement_id`. As noted in §3.4, a lookbook is also auto-created in `DRAFT` (titled "Final Lookbook") when an engagement becomes `FULFILLED`.

The stylist appends outfits to a `DRAFT` lookbook one at a time; each append supplies an outfit `name` and an optional `item_refs` list, is added to the `outfits` array, and increments `outfit_count` by one. The stylist then delivers the lookbook, moving it from `DRAFT` to `DELIVERED`. Delivery has two guards beyond the state check: the lookbook must hold at least one outfit (an `outfit_count` of zero is rejected with `ERR_LOOKBOOK_EMPTY`), and the engagement must be `ACTIVE` or `FULFILLED` (otherwise `ERR_ENGAGEMENT_NOT_ACTIVE`). Delivering a lookbook that is not `DRAFT` is rejected with `ERR_INVALID_LOOKBOOK_STATE`.

Once delivered, the client either accepts or asks for changes. A `Client` accepts a `DELIVERED` lookbook, moving it to the terminal `ACCEPTED` state, or requests a revision with optional `notes`, which returns the lookbook from `DELIVERED` to `DRAFT` and increments `revision_round` by one — a cyclic loop that repeats each time the client asks for another round. Accepting or requesting a revision on a lookbook that is not `DELIVERED` is rejected with `ERR_INVALID_LOOKBOOK_STATE`. Fetching a lookbook exposes `outfit_count` and `revision_round`; lookbooks under an engagement may be listed and filtered by `status`.

### 3.7. Invoicing, Payment, and Wallet Credit

A `PlatformAdmin` issues an **invoice** against an engagement that is `ACTIVE` or `FULFILLED`; issuance against an engagement in any other state is rejected with `ERR_INVALID_ENGAGEMENT_STATE`. Issuance snapshots the `line_items`: one line per `COMPLETED` session carrying that session's `charge_cents`, and one line per still-`PURCHASED` item carrying its `marked_up_price_cents`. The session lines are listed first (in session creation order), followed by the item lines (in item creation order), and each line records its `type` (`"session"` or `"item"`), the source `ref_id`, and its `amount_cents`. Cancelled sessions and returned items are excluded.

The totals are then computed and frozen on the invoice. The `subtotal_cents` is the sum of all line amounts. The `styling_fee_cents` is computed by taking ten percent of each individual line amount, rounding that per-line fee half up to whole cents, and then summing the rounded per-line fees — this per-line-then-sum order is deliberate and is not the same as rounding ten percent of the subtotal. The `volume_discount_cents` applies a tiered breakpoint on the subtotal: a subtotal of at least 100000 cents earns a ten-percent discount, a subtotal of at least 50000 cents but below 100000 earns a five-percent discount, and any smaller subtotal earns no discount; the discount is ten or five percent of the subtotal rounded half up in a single rounding. The `wallet_credit_applied_cents` is the lesser of the client's current `wallet_credit_cents` and the pre-credit amount, where the pre-credit amount is the subtotal plus the styling fee minus the volume discount. The `total_cents` is that pre-credit amount minus the wallet credit applied. At issuance the applied wallet credit is debited from the client's `wallet_credit_cents`. A new invoice is in `ISSUED` status and records its engagement via `engagement_id`.

A `Client` or a `PlatformAdmin` pays an `ISSUED` invoice, moving it to the terminal `PAID` state and stamping `paid_at` with the logical clock; paying an invoice that is not `ISSUED` is rejected with `ERR_INVALID_INVOICE_STATE`. If this is the client's first invoice ever to reach `PAID`, the client's `has_paid_invoice` flag is set true, and the system then evaluates any referral in `SIGNED_UP` status whose `referee_client_id` is this client and fires that referral's qualification cascade, described in §3.9. Fetching an invoice exposes its `subtotal_cents`, `styling_fee_cents`, `volume_discount_cents`, and `total_cents`; invoices under an engagement may be listed and filtered by `status`.

Separately, a `PlatformAdmin` may adjust a client's wallet directly by supplying an `amount_cents` (positive to credit, negative to debit) and an optional `reason`; the amount is added to `wallet_credit_cents`. The resulting balance can never be negative, so a debit that would drive it below zero is rejected with `ERR_VALIDATION`.

### 3.8. Subscriptions and Seasonal Refresh

A `Client` opens a **subscription** against its own client record with a `tier` of `SILVER` or `GOLD` and a recurring `monthly_fee_cents` greater than zero; it records its subscriber via `client_id` and begins in `PENDING`. A `PlatformAdmin` activates a `PENDING` subscription, which requires that the client's `wallet_credit_cents` be at least the `monthly_fee_cents`; if the wallet is short, activation is rejected with `ERR_INSUFFICIENT_WALLET`. Activation moves the subscription to `ACTIVE`, debits the `monthly_fee_cents` from the client's wallet, and grants seasonal-refresh credits: a `SILVER` subscription grants two and a `GOLD` subscription grants four, setting both `refresh_credits_total` and `refresh_credits_remaining` to that count. It also sets `current_period_start` to the logical clock and `current_period_end` to ninety days after that instant. Activating a subscription that is not `PENDING` is rejected with `ERR_INVALID_SUBSCRIPTION_STATE`.

A `Client` redeems one seasonal-refresh credit at a time against an `ACTIVE` subscription, which requires `refresh_credits_remaining` to be at least one and decrements it by one (it can never go below zero); redeeming with no credits left is rejected with `ERR_NO_REFRESH_CREDITS`, and redeeming against a subscription that is not `ACTIVE` is rejected with `ERR_INVALID_SUBSCRIPTION_STATE`. A `Client` may cancel a subscription that is `PENDING` or `ACTIVE`, moving it to the terminal `CANCELLED` state. Fetching a subscription exposes `refresh_credits_remaining` and the period dates; subscriptions under a client may be listed and filtered by `status`.

### 3.9. Referrals and the Reward Cascade

A `Client` creates a **referral** by supplying its own `referrer_client_id` (which must equal the acting client) and the invited prospect's `referee_email`. The referee email must not be the referrer's own email; a self-referral at creation is rejected with `ERR_SELF_REFERRAL`. The referral is created in `PENDING` with `referee_client_id` and `qualifying_invoice_id` unset, its `estimated_credit_cents` set to the flat projected reward of 5000 cents, and its `expires_at` set to ninety days after creation. Referrals may be listed and filtered by `referrer_client_id`, `referee_client_id`, `qualifying_invoice_id`, and `status`.

A `PlatformAdmin` records the signup, linking a registered `referee_client_id` and moving the referral from `PENDING` to `SIGNED_UP`. Signup requires the referral to be `PENDING` (otherwise `ERR_INVALID_REFERRAL_STATE`), the logical clock to be at or before `expires_at` (otherwise `ERR_REFERRAL_EXPIRED`), the referee client to exist, and the referee to differ from the referrer (a self-referral by id is again rejected with `ERR_SELF_REFERRAL`).

The reward is realized as a cascade off the referee's very first paid invoice, as introduced in §3.7. When a referral is `SIGNED_UP`, the paying invoice's engagement belongs to the referee client, and the referee had no prior paid invoice, the referral transitions automatically from `SIGNED_UP` to the terminal `CREDITED` state. At that point `qualifying_invoice_id` is set to that invoice, and `realized_credit_cents` is computed as the lesser of the cap of 10000 cents and ten percent of the qualifying invoice's `total_cents` rounded half up. That realized credit is then added to the referrer's `wallet_credit_cents`. Fetching a referral exposes its `estimated_credit_cents`, `realized_credit_cents`, and `status`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource, including state transitions and ledger adjustments, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/styling/stylists` | Create a stylist | PlatformAdmin |
| GET | `/styling/stylists/{id}` | Fetch one stylist | PlatformAdmin, Stylist, Client |
| POST | `/styling/clients/register` | Self-register a client | Anonymous |
| GET | `/styling/clients/{id}` | Fetch one client | PlatformAdmin, Stylist, Client |
| POST | `/styling/clients/{id}/assessments` | Create a DRAFT style assessment | Client |
| GET | `/styling/clients/{id}/assessments` | List a client's assessments | PlatformAdmin, Stylist, Client |
| POST | `/styling/assessments/{id}/complete` | Finalize an assessment | Stylist |
| POST | `/styling/engagements` | Open a DRAFT engagement | Client |
| GET | `/styling/engagements/{id}` | Fetch one engagement | PlatformAdmin, Stylist, Client |
| GET | `/styling/engagements` | List/filter engagements | PlatformAdmin, Stylist, Client |
| POST | `/styling/engagements/{id}/activate` | Activate an engagement | Client |
| POST | `/styling/engagements/{id}/cancel` | Cancel an engagement | Client |
| POST | `/styling/engagements/{id}/sessions` | Schedule a session | Client |
| GET | `/styling/sessions/{id}` | Fetch one session | PlatformAdmin, Stylist, Client |
| GET | `/styling/engagements/{id}/sessions` | List sessions of an engagement | PlatformAdmin, Stylist, Client |
| POST | `/styling/sessions/{id}/confirm` | Confirm a session | Stylist |
| POST | `/styling/sessions/{id}/reschedule` | Reschedule a session | Client, Stylist |
| POST | `/styling/sessions/{id}/complete` | Complete a session | Stylist |
| POST | `/styling/sessions/{id}/cancel` | Cancel a session | Client, Stylist |
| POST | `/styling/sessions/{id}/items` | Record a purchased item | Stylist |
| GET | `/styling/sessions/{id}/items` | List a session's purchased items | PlatformAdmin, Stylist, Client |
| POST | `/styling/purchase-items/{id}/return` | Return a purchased item | Stylist |
| POST | `/styling/engagements/{id}/lookbooks` | Create a DRAFT lookbook | Stylist |
| GET | `/styling/lookbooks/{id}` | Fetch one lookbook | PlatformAdmin, Stylist, Client |
| GET | `/styling/engagements/{id}/lookbooks` | List lookbooks of an engagement | PlatformAdmin, Stylist, Client |
| POST | `/styling/lookbooks/{id}/outfits` | Append an outfit | Stylist |
| POST | `/styling/lookbooks/{id}/deliver` | Deliver a lookbook | Stylist |
| POST | `/styling/lookbooks/{id}/accept` | Accept a delivered lookbook | Client |
| POST | `/styling/lookbooks/{id}/request-revision` | Request a lookbook revision | Client |
| POST | `/styling/clients/{id}/subscriptions` | Create a PENDING subscription | Client |
| GET | `/styling/subscriptions/{id}` | Fetch one subscription | PlatformAdmin, Stylist, Client |
| GET | `/styling/clients/{id}/subscriptions` | List a client's subscriptions | PlatformAdmin, Stylist, Client |
| POST | `/styling/subscriptions/{id}/activate` | Activate a subscription | PlatformAdmin |
| POST | `/styling/subscriptions/{id}/redeem-refresh` | Redeem a seasonal-refresh credit | Client |
| POST | `/styling/subscriptions/{id}/cancel` | Cancel a subscription | Client |
| POST | `/styling/referrals` | Create a referral | Client |
| GET | `/styling/referrals/{id}` | Fetch one referral | PlatformAdmin, Stylist, Client |
| GET | `/styling/referrals` | List/filter referrals | PlatformAdmin, Stylist, Client |
| POST | `/styling/referrals/{id}/signup` | Link a referee and sign up a referral | PlatformAdmin |
| POST | `/styling/engagements/{id}/invoices` | Issue an invoice | PlatformAdmin |
| GET | `/styling/invoices/{id}` | Fetch one invoice | PlatformAdmin, Stylist, Client |
| GET | `/styling/engagements/{id}/invoices` | List invoices of an engagement | PlatformAdmin, Stylist, Client |
| POST | `/styling/invoices/{id}/pay` | Pay an issued invoice | Client, PlatformAdmin |
| POST | `/styling/clients/{id}/wallet/adjustments` | Adjust a client's wallet balance | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_STYLIST_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_PURCHASE_ITEM_NOT_FOUND` | 404 |
| `ERR_LOOKBOOK_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVALID_ASSESSMENT_STATE` | 409 |
| `ERR_INVALID_ENGAGEMENT_STATE` | 409 |
| `ERR_INVALID_SESSION_STATE` | 409 |
| `ERR_INVALID_PURCHASE_ITEM_STATE` | 409 |
| `ERR_INVALID_LOOKBOOK_STATE` | 409 |
| `ERR_INVALID_SUBSCRIPTION_STATE` | 409 |
| `ERR_INVALID_INVOICE_STATE` | 409 |
| `ERR_INVALID_REFERRAL_STATE` | 409 |
| `ERR_ASSESSMENT_NOT_COMPLETED` | 409 |
| `ERR_ENGAGEMENT_NOT_ACTIVE` | 409 |
| `ERR_LOOKBOOK_EMPTY` | 422 |
| `ERR_STYLIST_TIME_CONFLICT` | 409 |
| `ERR_CLIENT_TIME_CONFLICT` | 409 |
| `ERR_INSUFFICIENT_PACKAGE_HOURS` | 409 |
| `ERR_INSUFFICIENT_WALLET` | 409 |
| `ERR_NO_REFRESH_CREDITS` | 409 |
| `ERR_SELF_REFERRAL` | 422 |
| `ERR_REFERRAL_EXPIRED` | 409 |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 |
