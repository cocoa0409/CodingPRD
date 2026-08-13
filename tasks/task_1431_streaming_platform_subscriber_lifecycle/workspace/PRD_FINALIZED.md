# Streaming Platform Subscriber Lifecycle API — Product Requirements Document

## 1. Introduction

Subscriber economics at a modern streaming service are won or lost in the long tail of lifecycle events: the trial that never converts, the renewal card that quietly fails, the cancellation that could have been deflected with a well-timed pause offer, the price increase that must honor legacy pricing for loyal households. This document specifies the Streaming Platform Subscriber Lifecycle API, a Netflix/Hulu-style subscription management system that governs the full arc of a subscriber relationship — from plan definition and signup attribution through trials, renewals, dunning, pauses, plan changes, price changes, win-back campaigns, and partner-billed reconciliation.

The API is built around two parallel concerns that must never drift apart: a subscriber-facing state axis (trial, active, past due, paused, cancelled, expired) and a billing-axis view of payment health (current, dunning, recovered) that runs alongside it. Operations teams additionally need deterministic, testable control over time itself — trial expirations, retry schedules, notice effectiveness, and retention measurements are all driven by a logical clock rather than wall-clock time. All resources are mounted under the `/v1` prefix. The sections that follow define the global contracts every endpoint obeys, then walk each business workflow in narrative form, then summarize the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to specify their operational capacity. The system recognizes four roles with exact spellings: `Subscriber`, `SupportAgent`, `PartnerBillingOps`, and `PlatformAdmin`. A request that arrives without both headers present and well-formed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` — a profile, a subscription, a save offer, a billing event — compare the resource's `account_id` foreign-key field (or the owning account reached through its parent chain) to `X-User-ID`, and a `Subscriber` may only act on resources owned by that account. When `X-User-Role` is `SupportAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; support agents act on behalf of subscribers on any account. When `X-User-Role` is `PartnerBillingOps`, `X-User-ID` is likewise an opaque operator identifier used only for attribution of partner reconciliation actions. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is again an opaque operator identifier; the platform administrator is a superset role that may invoke every operation available to the other three roles plus the administrative operations reserved to it. For the three opaque roles the server may record the identifier where a workflow writes an actor, but it never compares it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

Time in this system is a test-driving concern, not a wall-clock accident. The server maintains a logical clock whose value at startup is exactly `2026-08-01T00:00:00Z`; before any client adjusts it, every time-dependent rule in the system reads precisely this default, and the logical clock never falls back to wall-clock time. A `PlatformAdmin` may set the logical clock by supplying a `to_iso8601` instant; the capability responds with the resulting `now_utc`. All timestamps the system records — trial expirations, billing event times, notice announcements — are readings of this logical clock.

A second administrative capability advances time and runs every scheduled sweep in one motion: the caller supplies an `advance_to_iso8601` instant, and the server moves the logical clock forward and applies, in due order, trial-end conversions, dunning retries, pause expirations, price-change effectiveness, save-offer expirations, the retention sweeps at day 30 and day 90, and the password-sharing reconciliation pass. The response reports how many transitions fired via `applied_transitions` alongside the resulting `now_utc`. Any system transition described anywhere in §3 can fire through this sweep when its temporal precondition is met; a scheduled retry or transition whose due instant equals the current logical time fires exactly at that instant.

### 2.5. Common Resource Properties

Every primary resource in the system — plans, accounts, profiles, subscriptions, save offers, price change notices, win-back campaigns, partner billing records, and signup attributions — carries a standard set of system-managed fields:

- **Identifier (string):** A unique, server-minted UUID with no type prefix, named after the resource: `plan_id`, `account_id`, `profile_id`, `subscription_id`, `save_offer_id`, `price_change_notice_id`, `winback_campaign_id`, `partner_billing_record_id`, and `signup_attribution_id`. URL path parameters such as `{id}` always refer to this identifier.
- `created_at` (string): An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) recording when the resource was first created.
- `updated_at` (string): An ISO 8601 UTC timestamp, refreshed on any change to the resource's properties, including system-driven mutations such as cascades and sweep-applied transitions.
- `version` (integer): A system-managed integer that increments by one with every modification to the resource, and serves as the basis for optimistic concurrency control (§2.9).

Billing events are the deliberate exception: a `BillingEvent` is an immutable, append-only ledger entry and carries only its `billing_event_id` and `created_at` from the common set — both `updated_at` and `version` are absent, because a posted event is never modified.

### 2.6. Monetary Values and Precision

All monetary amounts in the system are represented as integer cents — `monthly_price_cents`, `amount_cents`, `old_price_cents`, `new_price_cents`, `expected_amount_cents`, `received_amount_cents`, `grandfathered_price_cents`, `outstanding_balance_cents`, and every computed charge or credit. Calculations are performed in whole cents: every derived monetary figure is rounded to 0 decimal places using the round-half-up method. Where a computation produces more than one monetary component (as in the upgrade proration of §3.5), each component is individually rounded half up to whole cents first, and only then are the rounded components combined — the net figure is a subtraction of already-rounded values, never a rounding of a raw difference. Signed amounts are permitted on the ledger: credits and refunds post as negative cent values.

### 2.7. The Billing Event Ledger

Every monetary movement and every billing-relevant milestone is recorded as an immutable `BillingEvent` on the account ledger. Each event carries its `billing_event_id`, the owning `account_id`, the `subscription_id` it relates to, an `event_type` drawn from `TRIAL_START`, `CHARGE`, `CHARGE_FAILED`, `REFUND`, `PRORATION_CREDIT`, `PRICE_CHANGE_APPLIED`, and `RECOVERY`, a signed `amount_cents` (negative for refunds and credits), and the `occurred_at_utc` instant read from the logical clock when the event was recorded. Operators posting manual events may attach an `external_reference` — mandatory when the event reports a partner-side charge — and a free-text `notes` annotation. A manually posted `CHARGE_FAILED` event is treated as a renewal charge failure under §3.4: posting one against an `ACTIVE` subscription whose `billing_state` is `CURRENT` moves the subscription to `PAST_DUE`, flips `billing_state` to `DUNNING`, and sets `dunning_attempt_count` to 1, and posting one against a subscription already in `PAST_DUE` with `billing_state` `DUNNING` increments `dunning_attempt_count`. The ledger is append-only: corrections are posted as new offsetting events rather than edits to existing ones.

The account's `outstanding_balance_cents` is a computed figure, never set directly: it is the sum of the amounts of unsettled `CHARGE_FAILED` events minus the amounts recovered since. The billing-event collection can be listed with filters on `account_id`, `subscription_id`, and `event_type`, and bounded to a time window through the `from_utc` and `to_utc` query parameters.

### 2.8. Validation Order and Error Precedence

Every request passes through a fixed validation pipeline, and the ordering is part of the contract: when several checks would fail, the failure reported is the one belonging to the earliest stage. A body that fails schema validation outright — a missing required field, a wrong-typed value, an invalid enum member — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Beyond schema sanity, the pipeline evaluates the following checks in strict priority order, each applying to the endpoints named with it:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and well-formed, on every endpoint; failures surface `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the presented role must be permitted to invoke the target endpoint, on every endpoint; failures surface `ERR_UNAUTHORIZED` (403).
3. **Existence** — every path parameter must identify an existing resource, validated strictly left-to-right along the path, so a missing parent masks everything beneath it; failures surface `ERR_NOT_FOUND` (404).
4. **State** — the target resource must be in a state from which the requested transition is allowed; this guards every state-transition endpoint (cancel, pause, resume, recover, accept, decline, reconcile, and the like) and surfaces `ERR_INVALID_STATE` (409).
5. **Account standing** — the account's status must permit the action: a `CLOSED` account blocks everything, and a `SUSPENDED` account blocks value-extending subscriber-facing mutations; failures surface `ERR_ACCOUNT_SUSPENDED` (409).
6. **Temporal validity** — a save offer must not be expired, a price-change notice must not yet be effective, and a pause duration must be valid; this stage guards save-offer acceptance, price-change cancellation, and direct pauses, and surfaces `ERR_OFFER_EXPIRED` (422).
7. **Referential integrity** — every Plan, Account, Subscription, SaveOffer, or Campaign referenced in a request body must exist and be mutually consistent (for example, the `subscription_id` recorded on a save offer must be the subscription the offer actually targets); failures on any endpoint carrying body foreign keys surface `ERR_REFERENTIAL_INTEGRITY` (422).
8. **Plan rules** — tier-direction rules on plan changes (a downgrade target's tier must rank below the current tier, an upgrade the reverse), the prohibition on subscribing to an archived plan, and profile/household limit rules; this guards subscription creation, plan changes, and profile creation, surfacing `ERR_PLAN_RULE_VIOLATION` (422).
9. **Profile and household caps** — the active profile count must remain below the plan's `max_profiles` and the distinct-household count must not exceed `max_households`; this guards profile creation and reactivation, surfacing `ERR_HOUSEHOLD_LIMIT_EXCEEDED` (422).
10. **Fiscal sufficiency** — a valid payment method with sufficient funds must back the charge, and a reconciliation delta must sit within tolerance unless an override is supplied; this guards dunning recovery, the first charge on subscription creation, and partner-record reconciliation, surfacing `ERR_PAYMENT_FAILED` (402).
11. **Outstanding balance** — unsuspension requires a zero outstanding balance; failures surface `ERR_OUTSTANDING_BALANCE` (402).
12. **Win-back window** — enrollment requires the days-since-cancellation figure to fall within the campaign's inclusive window; failures surface `ERR_WINBACK_INELIGIBLE` (422).
13. **Notice length** — a price change's effective date must be at least 30 days after its announcement; failures surface `ERR_PRICE_CHANGE_NOTICE_TOO_SHORT` (422).
14. **Pause cooldown** — a direct pause is allowed only when the account has not paused within the trailing 12 months; failures surface `ERR_PAUSE_NOT_ALLOWED` (422).

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each names the version field its request must carry. A plan change on a subscription must carry `expected_subscription_version`, holding the caller's last observed `version` of the target subscription; if the subscription's current `version` has advanced since that observation — because a price-change sweep, a scheduled downgrade, or a save-offer acceptance mutated it in the interim — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is written. On a plan change the stale-version check is evaluated only after the §2.8 state guard has passed, so a request whose target subscription is in a state that blocks plan changes surfaces `ERR_INVALID_STATE` even when the carried `expected_subscription_version` is stale. A reconciliation of a partner billing record must likewise carry `expected_partner_billing_record_version` holding the caller's last observed `version` of that record; a mismatch with the record's current `version` — for instance because a receipt was reported between the read and the reconcile attempt — is rejected with `ERR_STALE_VERSION` (HTTP 412). Win-back enrollment also takes `expected_subscription_version` in its payload, guarding the reactivation of the subscription it names under the same stale-version rule. Endpoints other than these do not accept a version field, and process mutations without an OCC check.

### 2.10. Dual-Axis Subscription State and Account-Level Cascades

A subscription is described by two state axes that evolve in parallel and must both be honored. The subscriber-facing axis, `subscription_status`, walks the lifecycle `TRIALING`, `ACTIVE`, `PAST_DUE`, `PAUSED`, `CANCELLED`, `EXPIRED`, with `CANCELLED` and `EXPIRED` terminal. The billing-health axis, `billing_state`, walks `CURRENT`, `DUNNING`, and `RECOVERED` with no terminal value, tracking payment retry independently of whether the subscription itself is live. Several transitions move both axes in one step — a failed renewal is simultaneously a fall into `PAST_DUE` and a fall into `DUNNING` — and the workflows in §3.4 spell out each pairing.

Account-level state changes cascade downward to keep the hierarchy consistent. When an account transitions to `SUSPENDED` — whether manually or because dunning exhausted on its subscription — every profile on the account becomes `DEACTIVATED`. The same profile cascade applies when an account is `CLOSED`. Each such cascade independently mutates the affected resources: every touched resource refreshes its `updated_at` and increments its `version`, so a client holding a stale snapshot of any cascaded resource will fail its next version-guarded write rather than silently overwrite the cascade.

## 3. Business Logic & Workflows

### 3.1. The Plan Catalog

Everything begins with the plan catalog. A `PlatformAdmin` defines a plan by supplying a stable business `plan_code` (unique among active plans), a human-facing `display_name`, a `tier` of `BASIC`, `STANDARD`, or `PREMIUM`, the list `monthly_price_cents`, a `trial_days` length (zero meaning the plan offers no trial), and the sharing envelope: `max_profiles` caps simultaneous profiles on a subscribing account, while `max_households` caps the distinct households allowed to stream. The tier values are ordinal — `BASIC` ranks below `STANDARD`, which ranks below `PREMIUM` — and this ordering alone decides whether a plan change is an upgrade or a downgrade (§3.5). Newly created plans carry `is_archived` set to false.

Retiring a plan does not strand its subscribers. Archiving flips `is_archived` to true; from that moment any attempt to create a new subscription on the plan is rejected with `ERR_PLAN_RULE_VIOLATION`, while every existing subscription on the plan continues untouched — billing, pauses, and even grandfathered pricing proceed exactly as before. The catalog can be browsed by any role, with optional filters on `tier` and `is_archived`.

### 3.2. Signup, Trial Conversion, and Signup Attribution

A subscriber relationship starts when a `PlatformAdmin` opens an account with an `email` (globally unique across the service), the holder's `full_name`, and an ISO-3166 alpha-2 `country_code`. Accounts that originate through a partner billing relationship record that relationship in `created_via_partner_id`; direct-billed accounts leave it null. A new account stands immediately in `ACTIVE` status, with `active_subscription_id` null until a subscription exists.

With an account in hand, a `Subscriber` (or a `SupportAgent` or `PlatformAdmin` acting for them) starts a subscription by naming the `account_id` and `plan_id`, optionally accompanied by the `content_id` of the asset that drove the signup and the acquisition `channel`. An account may hold at most one live subscription: attempting to create a second while one stands in `TRIALING`, `ACTIVE`, `PAST_DUE`, or `PAUSED` is rejected with `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION`. The plan's trial policy decides the entry state. When `trial_days` is greater than zero the subscription begins `TRIALING` with `trial_end_utc` set to the trial's expiry and a `TRIAL_START` billing event posted; when the plan offers no trial, the first charge is attempted immediately — a failed charge rejects the creation with `ERR_PAYMENT_FAILED` — and the subscription begins directly in `ACTIVE`. Either way `billing_state` opens at `CURRENT`, the account's `active_subscription_id` is set to the new subscription, and the subscription's timeline fields `period_start_utc` and `period_end_utc` bracket the current paid period (the period end is exclusive; a billing period runs a nominal 30 days). The creation request may also carry an optional `payment_method_token`; when supplied it is recorded as the account's payment method on file and backs the charges the system attempts for the subscription, and the simulated gateway declines a token equal to `FAIL` (case-insensitive) while approving any other supplied token. The immediate first charge on a no-trial creation therefore fails only when the caller supplies a declined token, and it succeeds when no token accompanies the creation. A payment method reaches the file only when one is supplied at subscription creation or through the recovery operation of §3.4.

Every signup also writes a `SignupAttribution` row keyed to the new subscription through the subscription's `signup_attribution_id`. The attribution captures the `content_id` — the empty string when the signup was organic rather than content-driven — and a `channel` of `ORGANIC`, `SEARCH`, `SOCIAL`, `AD`, `EMAIL`, or `REFERRAL`. Its `cohort_month` is the `YYYY-MM` month derived from the attribution row's own `created_at`. Attribution rows are append-only and carry no lifecycle state; what changes over time are the two retention flags, `retained_at_day_30` and `retained_at_day_90`, which the day-30 and day-90 retention sweeps recompute. A flag reads true exactly when the linked subscription's status is one of `TRIALING`, `ACTIVE`, `PAST_DUE`, or `PAUSED` at the instant precisely N days after the attribution's creation; a subscription that is `CANCELLED` or `EXPIRED` at that day reads false, and a subscription still live at the exact boundary instant counts as retained. Cohort reporting lists attributions filtered by `cohort_month`, `channel`, `content_id`, `account_id`, or `subscription_id`.

Trial conversion is the system's doing, not the subscriber's. Once the logical clock reaches `trial_end_utc`, the first renewal charge is attempted: on success the subscription moves `TRIALING → ACTIVE`, a `CHARGE` event is posted, and the account's `active_subscription_id` is confirmed against the matured subscription. If the trial ends with no valid payment method on file, the subscription instead falls `TRIALING → EXPIRED` with its `cancel_reason` recorded as `PAYMENT_FAILED`. If a payment method exists but the first charge fails, dunning runs against the trial (§3.4), and when that dunning is exhausted the subscription is cancelled with `cancel_reason` `PAYMENT_FAILED`. A subscriber who cancels during the trial lands in `CANCELLED` with `cancel_reason` `USER_REQUESTED`.

### 3.3. Profiles, Households, and Sharing Enforcement

Within an account, household members get their own profiles. Creating a profile takes the owning `account_id`, a `display_name`, an `is_kids` flag that restricts content rating, and a `household_id` — a logical household identifier such as a stable network or device fingerprint, which several profiles of the same account may share. A new profile starts `ACTIVE`, and the roster can be listed with filters on `account_id`, `profile_status`, or `household_id`.

Deactivation is always available: any of the subscriber-facing roles — or the system itself during an account cascade — can move a profile `ACTIVE → DEACTIVATED` with no precondition. Reactivation is the guarded direction. A profile can return `DEACTIVATED → ACTIVE` only when its owning account is `ACTIVE`, when the account's subscription stands in `TRIALING`, `ACTIVE`, or `PAST_DUE` (a `PAUSED` subscription blocks reactivation outright, surfacing `ERR_INVALID_STATE`), and when the number of active profiles on the account is strictly below the plan's `max_profiles` — hitting the cap surfaces `ERR_HOUSEHOLD_LIMIT_EXCEEDED`.

Password-sharing enforcement runs on a distinct-count rule over the account's `ACTIVE` profiles. The system counts the distinct `household_id` values across those profiles; the account violates the sharing policy only when that count is strictly greater than the plan's `max_households` — an account sitting exactly at the cap is compliant, and an account with no profiles counts zero households. The check fires when a profile is created, when one is reactivated, when streaming starts, and again in the nightly reconciliation pass of the scheduled sweep (§2.4). Violations at profile creation or reactivation are refused with `ERR_HOUSEHOLD_LIMIT_EXCEEDED`.

### 3.4. Renewal Billing, Dunning, and Involuntary Churn

Renewals are where revenue is defended. When a renewal charge fails on an `ACTIVE` subscription whose `billing_state` was `CURRENT`, the subscription falls `ACTIVE → PAST_DUE` and, in the same motion, `billing_state` flips to `DUNNING`, `dunning_attempt_count` is set to 1, and a `CHARGE_FAILED` event is posted to the ledger.

Retry timing follows a fixed backoff schedule measured in hours since the first failure: the first retry fires 24 hours after it, the second at 72 hours, the third at 120, the fourth at 168, and the fifth at 240. While `dunning_attempt_count` remains below five, each failure schedules the next retry at the offset corresponding to the current attempt count, and a retry whose scheduled instant equals the current logical time fires exactly then — the boundary is inclusive. Each retry outcome walks the billing axis: a success moves `billing_state` from `DUNNING` to `RECOVERED` and posts a `RECOVERY` event, while a failure posts another `CHARGE_FAILED` and increments `dunning_attempt_count`. Should a later renewal on a `RECOVERED` subscription fail again, the axis falls back to `DUNNING` with a fresh `CHARGE_FAILED`; conversely, the first successful charge that carries the subscription across a period boundary settles the axis from `RECOVERED` back to `CURRENT`.

Recovery heals both axes at once. Whether the retry succeeds on its own or the subscriber supplies a valid replacement `payment_method_token` through the recovery operation, the subscription moves `PAST_DUE → ACTIVE`, `billing_state` lands in `RECOVERED` (settling to `CURRENT` at the next successful period boundary), `dunning_attempt_count` resets to 0, and a `RECOVERY` event is posted. A recovery attempt whose replacement method fails its charge is rejected with `ERR_PAYMENT_FAILED`, and a manual recovery attempted after the attempt count has already reached five is rejected with `ERR_DUNNING_EXHAUSTED`.

Exhaustion is involuntary churn. Once `dunning_attempt_count` reaches five, the subscription transitions `PAST_DUE → EXPIRED`, its `cancel_reason` is set to `PAYMENT_FAILED`, the unpaid amount is added to the account's `outstanding_balance_cents`, and the owning account is automatically moved to `SUSPENDED` — the automatic suspension is precisely the case of a linked subscription expiring with `cancel_reason` `PAYMENT_FAILED` — which in turn deactivates every profile on the account per §2.10. A `PlatformAdmin` may also suspend an account manually at any time, with no precondition beyond the account being `ACTIVE`; the profile cascade is identical.

Standing back up requires a clean ledger. Unsuspension moves the account `SUSPENDED → ACTIVE` and is available to both `PlatformAdmin` and `SupportAgent`, but only while `outstanding_balance_cents` is zero — any residual balance rejects the request with `ERR_OUTSTANDING_BALANCE`. Closure is the terminal path: an account may move from `ACTIVE` or `SUSPENDED` to `CLOSED` only when no subscription stands in `TRIALING`, `ACTIVE`, `PAST_DUE`, or `PAUSED` and the outstanding balance is zero; closure deactivates all profiles and is irreversible. While an account is `SUSPENDED`, value-extending subscriber-facing mutations are blocked with `ERR_ACCOUNT_SUSPENDED`; a `CLOSED` account blocks everything. Accounts can be listed filtered by `account_status`, `email`, `created_via_partner_id`, or `active_subscription_id`.

### 3.5. Pauses, Resumes, and Plan Changes

A subscriber in good standing can step back without churning. A direct pause takes a `duration_months` argument and moves the subscription `ACTIVE → PAUSED`, setting `paused_until_utc` to the resume instant — the current logical time plus the pause duration — and posting a `PRORATION_CREDIT` event for the unused days of the current period. Direct pauses carry a cooldown: an account that has already paused within the trailing 12 months is refused with `ERR_PAUSE_NOT_ALLOWED`, and a pause request whose duration is invalid is refused with `ERR_OFFER_EXPIRED`. Pauses that arrive through an accepted save offer (§3.6) follow the same state change but are governed by the offer's validity instead of the cooldown.

The pause credit is computed with period-day arithmetic. The credit equals the subscription's current price — its `grandfathered_price_cents` when one is locked in, otherwise the plan's list `monthly_price_cents` — multiplied by the number of whole days remaining between now and `period_end_utc`, divided by the number of whole days in the period between `period_start_utc` and `period_end_utc`, with the result rounded half up to whole cents. That provisional credit posts immediately as a single negative `PRORATION_CREDIT` event. Resumption — whether automatic when the logical clock reaches `paused_until_utc` or early at the subscriber's request — returns the subscription `PAUSED → ACTIVE`, clears `paused_until_utc` to null, and posts a `CHARGE` for the prorated remaining period. When a subscription resumes before `period_end_utc`, the credit is recomputed using the actual paused duration, and the delta between the provisional credit and the final figure posts as a correcting billing event.

Plan changes split by direction, and the direction comes from the tier ordinals of §3.1. Every plan change must carry `expected_subscription_version` under the OCC rule of §2.9, and a stale version rejects the change with `ERR_STALE_VERSION` before anything is written. An upgrade — target tier ranking above the current — applies immediately: the subscription's `plan_id` becomes the `target_plan_id`, any `grandfathered_price_cents` lock is cleared, and proration is settled on the spot. The proration computes whole days remaining in the period and whole days in the period as above; the unused credit is the current price (grandfathered when locked, else list) times days remaining over days in period, rounded half up to whole cents; the prorated charge is the target plan's `monthly_price_cents` over the same day fraction, likewise rounded half up; and the net charge is the prorated charge minus the unused credit — each component rounded before the subtraction, never after. The posting lands on the ledger as a `CHARGE` and `PRORATION_CREDIT` pair — the `CHARGE` carries the prorated charge and the `PRORATION_CREDIT` carries the unused credit as a negative amount, so the pair sums to the net charge — and the subscription's `version` increments by one. A downgrade never applies mid-period: the target is parked in `pending_plan_id` and takes effect at the next period boundary. Requesting a direction that contradicts the tier ordering — or targeting an archived plan — is rejected with `ERR_PLAN_RULE_VIOLATION`.

Subscribers can preview the cost of a hypothetical change before committing. The proration-preview capability takes a `target_plan_id` and returns the `net_charge_cents`, `unused_credit_cents`, and `prorated_charge_cents` that the same formula produces, evaluated at the request's own instant — the preview is an optimistic estimate only and is never persisted to the ledger. The subscription collection itself can be filtered by `account_id`, `subscription_status`, `billing_state`, `plan_id`, `pending_plan_id`, `save_offer_id`, `signup_attribution_id`, or `price_change_notice_id`.

### 3.6. Cancellation Flows and Save Offers

Cancellation is the moment retention is won or lost. A cancellation request carries a `cancel_reason` drawn from `USER_REQUESTED`, `PAYMENT_FAILED`, `PRICE_REFUSAL`, `WINBACK_EXPIRED`, and `ADMIN`; a subscriber's own cancellation records `USER_REQUESTED`, while a `SupportAgent`-initiated cancellation outside the save-offer flow records `ADMIN`. From `ACTIVE` or `PAUSED` the subscription moves to `CANCELLED`; cancelling from `ACTIVE` additionally flips any save offer still `PRESENTED` on the subscription to `SUPERSEDED` and clears any scheduled `pending_plan_id`. Cancelling from `PAUSED` records `USER_REQUESTED`. All of `CANCELLED` and `EXPIRED` are terminal.

Before the cancellation lands, the service may make a save offer. Presenting an offer names the target `subscription_id` and an `offer_type` of `PAUSE_1M`, `PAUSE_3M`, `DOWNGRADE`, or `DISCOUNT_50_3M`, with `discount_pct` and `discount_duration_months` meaningful only for the discount type (both are 0 otherwise) and `target_plan_id` naming the downgrade destination only for the `DOWNGRADE` type (null otherwise). The offer is born `PRESENTED`, stamped with `presented_at_utc`, and given exactly 72 hours of life — its `expires_at_utc` is 72 hours after presentation. The subscription remembers the most recent offer presented against its latest cancel attempt through `save_offer_id`, and presenting a fresh offer on a subscription that already has one `PRESENTED` supersedes the older one. Offers list with filters on `subscription_id`, `offer_status`, `offer_type`, `account_id`, or `target_plan_id`.

Only the `Subscriber` may answer an offer. Declining moves it `PRESENTED → DECLINED` with no further effect; acceptance moves it `PRESENTED → ACCEPTED` and is guarded twice: the offer must not have reached `expires_at_utc` (an expired acceptance is rejected with `ERR_OFFER_EXPIRED`, and the sweep moves unanswered offers to `EXPIRED` at that instant), and the subscription must stand in `ACTIVE` or `TRIALING` (anything else is `ERR_INVALID_STATE`). What acceptance does beyond the state change depends on the type. Accepting `PAUSE_1M` or `PAUSE_3M` pauses the subscription per §3.5 with `paused_until_utc` set one or three months out, without touching the direct-pause cooldown. Accepting `DOWNGRADE` parks `target_plan_id` in the subscription's `pending_plan_id` to take effect at the next period. Accepting `DISCOUNT_50_3M` locks a discounted `grandfathered_price_cents` for `discount_duration_months`: the base is the subscription's existing `grandfathered_price_cents` when one is locked, otherwise the plan's list price; a `discount_pct` of 100 or more makes the price free, a `discount_pct` of zero or less keeps the base, and anything in between locks the base multiplied by the complement of the discount over one hundred, rounded half up to whole cents.

### 3.7. Price Changes and Grandfathering

Price increases are announced, never sprung. A `PlatformAdmin` announces a change by naming the `plan_id`, the `old_price_cents`, the `new_price_cents`, the `effective_at_utc` instant, and a `grandfather_period_months` length — zero meaning existing subscribers get no price protection. The notice is born `ANNOUNCED` and stamped with `announced_at_utc`; because subscribers deserve warning, an `effective_at_utc` less than 30 days after the announcement is rejected with `ERR_PRICE_CHANGE_NOTICE_TOO_SHORT`. A notice can be withdrawn while it is still pending — cancellation moves it `ANNOUNCED → CANCELLED` — but only before its effective instant; cancelling at or after effectiveness is rejected with `ERR_OFFER_EXPIRED`. Notices list with filters on `plan_id` and `notice_status`, and each subscription remembers the latest notice applicable to it through `price_change_notice_id`. Subscribers who decline the new price vote with the cancel flow, supplying `PRICE_REFUSAL` as their reason.

When the logical clock reaches `effective_at_utc`, the sweep moves the notice `ANNOUNCED → EFFECTIVE` and the change propagates in a pinned order: the old price is snapshotted first, then the months elapsed since announcement are computed as the number of whole 30-day months between `announced_at_utc` and `effective_at_utc`, then each subscription's new lock is decided, written, and only then is a `PRICE_CHANGE_APPLIED` billing event emitted for every affected subscription. The plan's `monthly_price_cents` becomes the `new_price_cents`. For each `TRIALING`, `ACTIVE`, or `PAST_DUE` subscription on the plan the carryover rule applies: a subscription holding no `grandfathered_price_cents` lock gains one equal to the notice's `old_price_cents` when `grandfather_period_months` is greater than zero, and otherwise pays the new price with no lock; a subscription already holding a lock keeps it only while the whole months elapsed since announcement remain strictly below `grandfather_period_months` — reaching the boundary clears the lock and the subscriber moves to the new price.

### 3.8. Win-Back Campaigns

Lapsed subscribers are a cohort worth courting. A `PlatformAdmin` drafts a win-back campaign with a `campaign_code` (unique among `DRAFT` and `ACTIVE` campaigns), a `discount_pct`, a `duration_months` span for the discount, an eligibility window bounded by `min_days_since_cancel` and `max_days_since_cancel`, and the `eligible_cancel_reasons` array naming which cancellation causes qualify. Campaigns are born `DRAFT`, go live on activation (`DRAFT → ACTIVE`), and are retired by closing (`ACTIVE → CLOSED`); only `ACTIVE` campaigns ever qualify an account. The catalog lists with a `campaign_status` filter.

Eligibility is a computed read, never a stored flag. For a given account the system locates the most recent `CANCELLED` or `EXPIRED` subscription, computes `days_since_cancel` as the whole days between that subscription's `updated_at` and the current logical time, and matches it against every `ACTIVE` campaign whose window inclusively contains that figure — both bounds count — and whose `eligible_cancel_reasons` contain the subscription's `cancel_reason`. The read returns the matching `eligible_campaign_ids` together with the `days_since_cancel` figure, ordered deterministically by each campaign's `created_at` ascending — never by identifier. The eligibility rules of §2.8 apply on enrollment: an account whose window or cancel reason fails every campaign is refused with `ERR_WINBACK_INELIGIBLE`.

Enrollment reactivates the relationship. Enrolling an account into a campaign names the `winback_campaign_id` and carries `expected_subscription_version` for the subscription being revived under the stale-version rule. The most recent cancelled or expired subscription returns to `ACTIVE` with its `cancel_reason` left unchanged as a historical record, its `grandfathered_price_cents` is locked at the plan's list `monthly_price_cents` multiplied by the complement of the campaign's `discount_pct` over one hundred and rounded half up to whole cents, holding for the campaign's `duration_months`, the subscription's `version` increments by one, and a `CHARGE` event posts for the first discounted month.

### 3.9. Partner-Billed Subscription Reconciliation

Accounts billed through platforms like Apple, Google, or Roku settle on a reconciliation cycle rather than a card charge. A `PartnerBillingOps` operator (or `PlatformAdmin`) registers an expected cycle by naming the `partner_code`, the billed `account_id`, the partner-side `partner_subscription_ref`, the `expected_amount_cents` due for the cycle, and the `period_start_utc` and `period_end_utc` bracketing it; the record is born `EXPECTED`. Accounts that originated through such a relationship point back to it via `created_via_partner_id`, and the records list with filters on `account_id`, `partner_code`, or `report_status`.

When the partner remits, reporting the receipt with the actual `received_amount_cents` moves the record `EXPECTED → RECEIVED`. Reconciliation then compares reality to expectation, and the call is version-guarded: it must carry `expected_partner_billing_record_version`, and a stale snapshot is rejected with `ERR_STALE_VERSION` before anything is written; a successful reconciliation increments the record's `version` by one. The delta is the received amount minus the expected amount. When the absolute delta is within the auto-reconcile tolerance of 500 cents — and exactly 500 counts as within — the record moves `RECEIVED → RECONCILED` and a `CHARGE` event for the received amount posts to the linked subscription's ledger. When the absolute delta exceeds the tolerance — 501 cents is already over — the record instead moves to `DISCREPANCY` for human review.

A discrepancy has two exits. A `PlatformAdmin` may reconcile it by force: the reconcile call on a `DISCREPANCY` record requires `override` set to true, and a call without the override is rejected with `ERR_RECONCILE_DELTA_EXCEEDS_TOLERANCE`; a forced reconcile moves the record to `RECONCILED`, posts the `CHARGE` for the received amount, and logs the difference in the event's `notes`. Alternatively the administrator may write the cycle off, moving the record `DISCREPANCY → WRITE_OFF` with no charge posted. Both `RECONCILED` and `WRITE_OFF` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource, execute a state transition, or produce a computed read return a `200 OK` status code. All paths below are relative to the service root and already include the `/v1` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the server's logical clock (test-driving) | PlatformAdmin |
| POST | `/v1/_sweeps/run` | Advance the logical clock and run all scheduled sweeps | PlatformAdmin |
| POST | `/v1/plans` | Create a plan | PlatformAdmin |
| GET | `/v1/plans` | List plans | PlatformAdmin, SupportAgent, PartnerBillingOps, Subscriber |
| GET | `/v1/plans/{id}` | Get plan by id | PlatformAdmin, SupportAgent, PartnerBillingOps, Subscriber |
| POST | `/v1/plans/{id}/archive` | Archive a plan (existing subscriptions grandfathered) | PlatformAdmin |
| POST | `/v1/accounts` | Open a new subscriber account | PlatformAdmin |
| GET | `/v1/accounts` | List accounts | PlatformAdmin, SupportAgent, PartnerBillingOps |
| GET | `/v1/accounts/{id}` | Get account by id | PlatformAdmin, SupportAgent, PartnerBillingOps, Subscriber |
| POST | `/v1/accounts/{id}/suspend` | Manually suspend an account | PlatformAdmin |
| POST | `/v1/accounts/{id}/unsuspend` | Unsuspend an account; requires zero outstanding balance | PlatformAdmin, SupportAgent |
| POST | `/v1/accounts/{id}/close` | Close an account (terminal) | PlatformAdmin, SupportAgent |
| GET | `/v1/accounts/{id}/winback-eligibility` | Computed read of win-back eligibility for an account | PlatformAdmin, SupportAgent, Subscriber |
| POST | `/v1/accounts/{id}/winback-enroll` | Enroll an account into a win-back campaign | PlatformAdmin, SupportAgent, Subscriber |
| POST | `/v1/profiles` | Create a profile on an account | Subscriber, PlatformAdmin, SupportAgent |
| GET | `/v1/profiles` | List profiles (filterable) | PlatformAdmin, SupportAgent, PartnerBillingOps, Subscriber |
| GET | `/v1/profiles/{id}` | Get profile | PlatformAdmin, SupportAgent, PartnerBillingOps, Subscriber |
| POST | `/v1/profiles/{id}/deactivate` | Deactivate a profile | Subscriber, PlatformAdmin, SupportAgent |
| POST | `/v1/profiles/{id}/reactivate` | Reactivate a profile; enforces plan limits | Subscriber, PlatformAdmin, SupportAgent |
| POST | `/v1/subscriptions` | Create a new subscription on an account | Subscriber, PlatformAdmin, SupportAgent |
| GET | `/v1/subscriptions` | List subscriptions | PlatformAdmin, SupportAgent, PartnerBillingOps, Subscriber |
| GET | `/v1/subscriptions/{id}` | Get subscription | PlatformAdmin, SupportAgent, PartnerBillingOps, Subscriber |
| POST | `/v1/subscriptions/{id}/cancel` | Cancel a subscription (user or support initiated) | Subscriber, PlatformAdmin, SupportAgent |
| POST | `/v1/subscriptions/{id}/pause` | Direct pause (no save offer) — subject to 12-month cooldown | Subscriber, PlatformAdmin, SupportAgent |
| POST | `/v1/subscriptions/{id}/resume` | Resume a paused subscription | Subscriber, PlatformAdmin, SupportAgent |
| POST | `/v1/subscriptions/{id}/recover` | Recover from dunning with a replacement payment method | Subscriber, PlatformAdmin, SupportAgent |
| POST | `/v1/subscriptions/{id}/change-plan` | Change plan (upgrade applies immediately with proration; downgrade scheduled) | Subscriber, PlatformAdmin, SupportAgent |
| GET | `/v1/subscriptions/{id}/proration-preview` | Compute optimistic proration preview for a hypothetical plan change | Subscriber, PlatformAdmin, SupportAgent |
| POST | `/v1/save-offers` | Present a save offer to a subscriber | Subscriber, PlatformAdmin, SupportAgent |
| GET | `/v1/save-offers` | List save offers | PlatformAdmin, SupportAgent, Subscriber |
| GET | `/v1/save-offers/{id}` | Get save offer | PlatformAdmin, SupportAgent, Subscriber |
| POST | `/v1/save-offers/{id}/accept` | Accept a save offer | Subscriber |
| POST | `/v1/save-offers/{id}/decline` | Decline a save offer | Subscriber |
| GET | `/v1/billing-events` | List billing events | PlatformAdmin, SupportAgent, PartnerBillingOps |
| GET | `/v1/billing-events/{id}` | Get billing event | PlatformAdmin, SupportAgent, PartnerBillingOps |
| POST | `/v1/billing-events` | Post a manual billing event (refund, adjustment, partner-reported charge) | PlatformAdmin, SupportAgent, PartnerBillingOps |
| POST | `/v1/price-change-notices` | Announce a price change | PlatformAdmin |
| GET | `/v1/price-change-notices` | List price change notices | PlatformAdmin, SupportAgent, PartnerBillingOps |
| GET | `/v1/price-change-notices/{id}` | Get a price change notice | PlatformAdmin, SupportAgent, PartnerBillingOps |
| POST | `/v1/price-change-notices/{id}/cancel` | Cancel an announced price change | PlatformAdmin |
| POST | `/v1/winback-campaigns` | Create a win-back campaign | PlatformAdmin |
| GET | `/v1/winback-campaigns` | List win-back campaigns | PlatformAdmin, SupportAgent, PartnerBillingOps |
| GET | `/v1/winback-campaigns/{id}` | Get win-back campaign | PlatformAdmin, SupportAgent, PartnerBillingOps |
| POST | `/v1/winback-campaigns/{id}/activate` | Activate a win-back campaign | PlatformAdmin |
| POST | `/v1/winback-campaigns/{id}/close` | Close a win-back campaign | PlatformAdmin |
| POST | `/v1/partner-billing-records` | Register an expected partner billing cycle | PartnerBillingOps, PlatformAdmin |
| GET | `/v1/partner-billing-records` | List partner billing records | PartnerBillingOps, PlatformAdmin, SupportAgent |
| GET | `/v1/partner-billing-records/{id}` | Get partner billing record | PartnerBillingOps, PlatformAdmin, SupportAgent |
| POST | `/v1/partner-billing-records/{id}/report-receipt` | Report receipt of partner payment | PartnerBillingOps |
| POST | `/v1/partner-billing-records/{id}/reconcile` | Reconcile a partner billing record | PartnerBillingOps, PlatformAdmin |
| POST | `/v1/partner-billing-records/{id}/write-off` | Write off a discrepancy | PlatformAdmin |
| GET | `/v1/signup-attributions` | List signup attributions (cohort reporting) | PlatformAdmin, SupportAgent |
| GET | `/v1/signup-attributions/{id}` | Get signup attribution | PlatformAdmin, SupportAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ACCOUNT_SUSPENDED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_PLAN_RULE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_HOUSEHOLD_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PAYMENT_FAILED` | 402 Payment Required |
| `ERR_OUTSTANDING_BALANCE` | 402 Payment Required |
| `ERR_WINBACK_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PRICE_CHANGE_NOTICE_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_PAUSE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_DUNNING_EXHAUSTED` | 409 Conflict |
| `ERR_RECONCILE_DELTA_EXCEEDS_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION` | 409 Conflict |
